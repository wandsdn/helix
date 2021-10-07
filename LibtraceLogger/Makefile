COMPILER=gcc
FLAGS=-g -Wall
LIBTRACE_FLAGS=-ltrace -lwandio

usage: cleanMake

cleanMake: clean logger processPKTGEN

logger: logger.c
	$(COMPILER) $(FLAGS) -o logger logger.c $(LIBTRACE_FLAGS)

processPKTGEN: processPKTGEN.c
	$(COMPILER) $(FLAGS) -o processPKTGEN processPKTGEN.c $(LIBTRACE_FLAGS)

clean:
	rm -rf *\.o logger processPKTGEN

help:
	@echo " " >&2
	@echo "A cleanMake target is executed by default!" >&2
	@echo " " >&2
	@echo "Here are the supported make targets!" >&2
	@echo "\tmake logger        - Compile logger" >&2
	@echo "\tmake processPKTGEN - Compile PKTGEN processor" >&2
	@echo "\tmake cleanMake     - Clean the entire project and re-compile" >&2
	@echo "\tmake clean         - Clean the project" >&2
	@echo "\tmake helo          - Display this usage message" >&2
	@echo " ">&2
