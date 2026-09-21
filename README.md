__Current version 3.9#8.2.__

Picat is a simple, and yet powerful, logic-based
multi-paradigm programming language aimed for
general-purpose applications. Picat is a rule-based
language, in which predicates, functions, and actors are
defined with pattern-matching rules. Picat incorporates
many declarative language features for better productivity
of software development, including explicit
non-determinism, explicit unification, functions, list
comprehensions, constraints, and tabling. Picat also
provides imperative language constructs, such as
assignments and loops, for programming everyday things. The
Picat implementation, which is based on a well-designed
virtual machine and incorporates a memory manager that
garbage-collects and expands the stacks and data areas when
needed, is efficient and scalable. Picat can be used for
not only symbolic computations, which is a traditional
application domain of declarative languages, but also for
scripting and modeling tasks. 

Compared with functional and scripting languages, the
support of explicit unification, explicit non-determinism,
tabling, and constraints makes Picat more suitable for
symbolic computations. Compared with Prolog, Picat is
arguably more expressive and scalable: it is not rare to
find problems for which Picat requires an order of
magnitude fewer lines of code to describe than Prolog and
Picat can be significantly faster than Prolog because
pattern-matching facilitates indexing of rules. 

The Picat system is written in both C and Picat. The
package has the following folders and files:
- Picat/README  --   this file
- Picat/doc     --   documentation
- Picat/exs     --   program examples
- Picat/emu     --   the C/C++ source code of the engine
- Picat/lib     --   library modules
- Picat/lib2  --   library modules, not preloaded

The folder "Picat/emu" contains the C source code needed to
make Picat's standalone executable. It also contains the C
source code of Espresso, SAT solvers (maple and lingeling),
which are used by Picat. This folder also contains make files
for different platforms.

The folder "Picat/lib" contains library modules. There are
three types of library modules:

pre-loaded and pre-imported: 
---------------------------
The symbols defined in this type of modules are directly
available to applications, and it's unnecessary to import
them. This type includes: "basic.pi", "io.pi", "math.pi",
and "sys.pi".

pre-loaded but not pre-imported: 
-------------------------------
These modules are included in the executable. However,
applications need to import them in order to access the
functions, predicates, and constraints defined in the
modules. No setting of the environment variable PICATPATH is
required. This type includes: "cp.pi", "mip.pi", "nn.pi",
"os.pi", "planner.pi", "sat.pi", "smt.pi", and "util.pi".

not pre-loaded, and not pre-imported: 
-------------------------------------
These modules, which are mainly developed by third parties,
are not included in the executable. In order to import any
of these modules, applications must set the environment
variable PICATPATH to include the folder, in which the module
resides, or start picat with the option "-path" set.

Laya decision-model inference (optional)
----------------------------------------
Picat can run the Laya typed-decision model
(https://huggingface.co/convaiinnovations/laya) in-process, through
the laya.cpp runtime (ggml) that is vendored as the git submodule
"emu/laya.cpp" and exposed as the module "lib2/laya.pi". Laya answers
choice / score / yes-no questions about a piece of text or a JSON
document in one forward pass, on the CPU or on CUDA GPUs.

Build requirements: a C++20 compiler, CMake 3.27+, ICU and
nlohmann-json (on Debian-like systems: libicu-dev and
nlohmann-json3-dev). CUDA is optional.

    git submodule update --init --recursive
    cmake -S . -B build -G Ninja -DPICAT_LAYA=ON      # add -DPICAT_LAYA_CUDA=ON for GPUs
    cmake --build build --parallel
    python3 emu/laya.cpp/scripts/download_model.py --variant english
    PICATPATH=lib2 build/emu/picat exs/laya/triage.pi emu/laya.cpp/models/laya

The module provides laya_load/1-2, laya_predict/3, laya_predict_batch/2,
laya_predict_json/2, laya_backend/1 and laya_destroy/1, plus the
question constructors choice/2, score/2 and noul/1-2. See the header
of "lib2/laya.pi" for the data conventions and "exs/laya/triage.pi"
for a complete example. Without -DPICAT_LAYA=ON nothing changes in
the executable.

Please contact:
- picat@picat-lang.org
- picat-lang@googlegroups.com 
