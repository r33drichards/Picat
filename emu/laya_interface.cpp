/********************************************************************
 *   File   : laya_interface.cpp
 *   Purpose: In-process Laya typed-decision inference for Picat.
 *
 *   Wraps the laya.cpp runtime (emu/laya.cpp, ggml based) as Picat
 *   built-ins.  The Picat-facing API lives in lib2/laya.pi; the
 *   predicates registered here are the low-level "bp." entry points
 *   that module calls.
 *
 *   Term <-> JSON conventions (see lib2/laya.pi for the Picat side):
 *     integer / float            <-> JSON number
 *     atom true / false / null   <-> JSON literal
 *     other atom                  -> JSON string
 *     Picat string (char list)   <-> JSON string   ([] is "")
 *     list whose elements are all K=V  -> JSON object (order preserved)
 *     other list, or {...} array  -> JSON array
 *     JSON object                 -> laya_obj([Key=Value,...]), Key an atom
 *                                    (or an integer for digit-only keys)
 *
 *   Built as part of the Picat executable when configured with
 *   -DPICAT_LAYA=ON (see CMakeLists.txt); everything is guarded by LAYA.
 ********************************************************************/
#ifdef LAYA

#include "laya/runtime.hpp"
#include "ggml.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" {
#include "picat.h"
#include "picat_utilities.h"
}

namespace {

using laya::json;

std::map<long, std::unique_ptr<laya::agent>> agents;
long next_agent_id = 1;
bool logging_configured = false;

struct laya_failure : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// ---------------------------------------------------------------- helpers

std::string term_to_string(TERM t) {
    char* raw = picat_string_to_cstring(t);
    std::string text(raw);
    free(raw);
    return text;
}

TERM string_to_term(const std::string& text) {
    // cstring_to_picat decodes UTF-8 into one char atom per code point.
    return cstring_to_picat(const_cast<char*>(text.data()), int(text.size()));
}

TERM list_from_terms(const std::vector<TERM>& items) {
    TERM tail = picat_build_nil();
    for (auto it = items.rbegin(); it != items.rend(); ++it) {
        TERM cell = picat_build_list();
        picat_unify(picat_get_car(cell), *it);
        picat_unify(picat_get_cdr(cell), tail);
        tail = cell;
    }
    return tail;
}

bool is_pair(TERM t) {
    return picat_is_structure(t) && picat_get_struct_arity(t) == 2 &&
           std::strcmp(picat_get_struct_name(t), "=") == 0;
}

// A non-empty proper list whose elements are all Key=Value pairs.
bool is_pair_list(TERM t) {
    if (!picat_is_list(t)) return false;
    while (picat_is_list(t)) {
        if (!is_pair(picat_get_car(t))) return false;
        t = picat_get_cdr(t);
    }
    return picat_is_nil(t);
}

std::string key_to_string(TERM key) {
    if (picat_is_nil(key)) return "";
    if (picat_is_string(key)) return term_to_string(key);
    if (picat_is_atom(key)) return picat_get_atom_name(key);
    if (picat_is_integer(key)) return std::to_string(picat_get_integer(key));
    throw laya_failure("object keys must be atoms, strings or integers");
}

json term_to_json(TERM t) {
    if (picat_is_var(t)) throw laya_failure("request contains an unbound variable");
    if (picat_is_integer(t)) return json(static_cast<long long>(picat_get_integer(t)));
    if (picat_is_float(t)) return json(picat_get_float(t));
    if (picat_is_nil(t)) return json("");
    if (picat_is_atom(t)) {
        const char* name = picat_get_atom_name(t);
        if (std::strcmp(name, "true") == 0) return json(true);
        if (std::strcmp(name, "false") == 0) return json(false);
        if (std::strcmp(name, "null") == 0) return json(nullptr);
        return json(std::string(name));
    }
    if (picat_is_string(t)) return json(term_to_string(t));
    if (picat_is_list(t)) {
        if (is_pair_list(t)) {
            json object = json::object();
            for (TERM l = t; picat_is_list(l); l = picat_get_cdr(l)) {
                TERM pair = picat_get_car(l);
                object[key_to_string(picat_get_arg(1, pair))] = term_to_json(picat_get_arg(2, pair));
            }
            return object;
        }
        json array = json::array();
        TERM l = t;
        for (; picat_is_list(l); l = picat_get_cdr(l)) array.push_back(term_to_json(picat_get_car(l)));
        if (!picat_is_nil(l)) throw laya_failure("request contains a partial list");
        return array;
    }
    if (picat_is_array(t)) {
        json array = json::array();
        int arity = picat_get_struct_arity(t);
        for (int i = 1; i <= arity; ++i) array.push_back(term_to_json(picat_get_arg(i, t)));
        return array;
    }
    if (picat_is_structure(t)) {
        std::string name = picat_get_struct_name(t);
        if (name == "$hshtb")
            throw laya_failure("maps must be converted to Key=Value lists (use the laya module, not bp.pi_laya_* directly)");
        throw laya_failure("unsupported term in request: structure " + name + "/" +
                           std::to_string(picat_get_struct_arity(t)));
    }
    throw laya_failure("unsupported term in request");
}

// Object keys become atoms, except canonical non-negative integers ("0",
// "17"), which become Picat integers so score legends index naturally.
TERM key_to_term(const std::string& key) {
    bool numeric = !key.empty() && key.size() <= 18 && (key == "0" || key[0] != '0');
    for (char c : key) numeric = numeric && c >= '0' && c <= '9';
    if (numeric) return picat_build_integer(std::stoll(key));
    return picat_build_atom(key.c_str());
}

TERM json_to_term(const json& value) {
    LOCAL_OVERFLOW_CHECK("laya_json_to_term");
    switch (value.type()) {
    case json::value_t::null: return picat_build_atom("null");
    case json::value_t::boolean: return picat_build_atom(value.get<bool>() ? "true" : "false");
    case json::value_t::number_integer: return picat_build_integer(static_cast<BPLONG>(value.get<long long>()));
    case json::value_t::number_unsigned: return picat_build_integer(static_cast<BPLONG>(value.get<unsigned long long>()));
    case json::value_t::number_float: return picat_build_float(value.get<double>());
    case json::value_t::string: return string_to_term(value.get<std::string>());
    case json::value_t::array: {
        std::vector<TERM> items;
        items.reserve(value.size());
        for (const auto& element : value) items.push_back(json_to_term(element));
        return list_from_terms(items);
    }
    case json::value_t::object: {
        std::vector<TERM> pairs;
        pairs.reserve(value.size());
        for (auto it = value.begin(); it != value.end(); ++it) {
            TERM pair = picat_build_structure(const_cast<char*>("="), 2);
            picat_unify(picat_get_arg(1, pair), key_to_term(it.key()));
            picat_unify(picat_get_arg(2, pair), json_to_term(it.value()));
            pairs.push_back(pair);
        }
        TERM object = picat_build_structure(const_cast<char*>("laya_obj"), 1);
        picat_unify(picat_get_arg(1, object), list_from_terms(pairs));
        return object;
    }
    default:
        throw laya_failure("unsupported JSON value in result");
    }
}

int raise_laya_error(const std::string& message) {
    TERM error = picat_build_structure(const_cast<char*>("laya_error"), 1);
    picat_unify(picat_get_arg(1, error), string_to_term(message));
    bp_exception = error;
    return PICAT_ERROR;
}

laya::agent& agent_from_term(TERM handle) {
    if (!picat_is_structure(handle) || picat_get_struct_arity(handle) != 1 ||
        std::strcmp(picat_get_struct_name(handle), "laya") != 0)
        throw laya_failure("laya agent expected");
    TERM id_term = picat_get_arg(1, handle);
    if (!picat_is_integer(id_term)) throw laya_failure("laya agent expected");
    auto it = agents.find(picat_get_integer(id_term));
    if (it == agents.end()) throw laya_failure("laya agent has been destroyed or was never loaded");
    return *it->second;
}

int truthy(TERM t) {
    if (picat_is_integer(t)) return picat_get_integer(t) != 0;
    if (picat_is_atom(t)) return std::strcmp(picat_get_atom_name(t), "true") == 0;
    throw laya_failure("option flags must be 0/1 or true/false");
}

void configure_logging() {
    if (logging_configured) return;
    logging_configured = true;
    ggml_log_set([](ggml_log_level level, const char* text, void*) {
        if (level >= GGML_LOG_LEVEL_WARN) std::fputs(text, stderr);
    }, nullptr);
}

template <typename F>
int guarded(F&& body) {
    try {
        return body();
    } catch (const std::exception& e) {
        return raise_laya_error(e.what());
    } catch (...) {
        return raise_laya_error("unknown failure inside laya");
    }
}

} // namespace

// ------------------------------------------------------------- built-ins

// pi_laya_load(Dir, Cuda, Bf16, Flash, TensorCore, Agent)
extern "C" int pi_laya_load() {
    return guarded([] {
        TERM dir = picat_get_call_arg(1, 6);
        TERM cuda = picat_get_call_arg(2, 6);
        TERM bf16 = picat_get_call_arg(3, 6);
        TERM flash = picat_get_call_arg(4, 6);
        TERM tensor_core = picat_get_call_arg(5, 6);
        TERM result = picat_get_call_arg(6, 6);

        std::string directory;
        if (picat_is_atom(dir)) directory = picat_get_atom_name(dir);
        else if (picat_is_string(dir) || picat_is_nil(dir)) directory = term_to_string(dir);
        else throw laya_failure("model directory must be a string or atom");

        configure_logging();
        auto agent = std::make_unique<laya::agent>(directory, truthy(cuda), truthy(bf16), truthy(flash), truthy(tensor_core));
        long id = next_agent_id++;
        agents[id] = std::move(agent);

        TERM handle = picat_build_structure(const_cast<char*>("laya"), 1);
        picat_unify(picat_get_arg(1, handle), picat_build_integer(id));
        return picat_unify(result, handle);
    });
}

// pi_laya_destroy(Agent)
extern "C" int pi_laya_destroy() {
    return guarded([] {
        TERM handle = picat_get_call_arg(1, 1);
        agent_from_term(handle);
        agents.erase(picat_get_integer(picat_get_arg(1, handle)));
        return PICAT_TRUE;
    });
}

// pi_laya_destroy_all
extern "C" int pi_laya_destroy_all() {
    agents.clear();
    return PICAT_TRUE;
}

// pi_laya_backend(Agent, Name)
extern "C" int pi_laya_backend() {
    return guarded([] {
        laya::agent& agent = agent_from_term(picat_get_call_arg(1, 2));
        return picat_unify(picat_get_call_arg(2, 2), string_to_term(agent.backend_name()));
    });
}

// pi_laya_predict(Agent, Requests, Results)
//   Requests: a Picat list of request objects (each a Key=Value list with
//   keys state and questions).  Results: a list of laya_obj terms.
extern "C" int pi_laya_predict() {
    return guarded([] {
        laya::agent& agent = agent_from_term(picat_get_call_arg(1, 3));
        json requests = term_to_json(picat_get_call_arg(2, 3));
        if (!requests.is_array()) requests = json::array({requests});
        json results = agent.predict(requests);
        return picat_unify(picat_get_call_arg(3, 3), json_to_term(results));
    });
}

// pi_laya_predict_json(Agent, RequestJson, ResultJson)
//   Raw pass-through: JSON text in, JSON text out (a JSON array of results).
extern "C" int pi_laya_predict_json() {
    return guarded([] {
        laya::agent& agent = agent_from_term(picat_get_call_arg(1, 3));
        TERM text = picat_get_call_arg(2, 3);
        if (!picat_is_string(text) && !picat_is_nil(text)) throw laya_failure("request must be a JSON string");
        json requests = json::parse(term_to_string(text));
        if (!requests.is_array()) requests = json::array({requests});
        json results = agent.predict(requests);
        return picat_unify(picat_get_call_arg(3, 3), string_to_term(results.dump()));
    });
}

extern "C" int laya_cpreds() {
    insert_cpred(const_cast<char*>("pi_laya_load"), 6, pi_laya_load);
    insert_cpred(const_cast<char*>("pi_laya_destroy"), 1, pi_laya_destroy);
    insert_cpred(const_cast<char*>("pi_laya_destroy_all"), 0, pi_laya_destroy_all);
    insert_cpred(const_cast<char*>("pi_laya_backend"), 2, pi_laya_backend);
    insert_cpred(const_cast<char*>("pi_laya_predict"), 3, pi_laya_predict);
    insert_cpred(const_cast<char*>("pi_laya_predict_json"), 3, pi_laya_predict_json);
    return PICAT_TRUE;
}

#endif // LAYA
