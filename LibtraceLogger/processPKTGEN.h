/*
    Header file of process pktgen which contains all the includes used in the
    processPKTGEN.c source file and defines all method prototypes. For more detailed
    description of each method functionality please refer to processPKTGEN.c.
*/

#ifndef PROCESS_PKTGEN_H
#define PROCESS_PKTGEN_H

#include "libtrace.h"
#include <time.h>
#include <stdlib.h>

#define TRUE            1
#define FALSE           0
#define PKTGEN_MAGIC    0xBE9BE955


/* -------------------- METHOD PROTOTYPES ------------------- */


static bool isPktgen(uint32_t *data, uint32_t *seq, struct timeval *tv);

static char *timeval_to_str(struct timeval *tv);

static bool processSecondary(libtrace_packet_t *packet);

static void processPrimary(libtrace_packet_t *packet);

static void cleanUp(libtrace_t *prim_trace, libtrace_t *sec_trace,
             libtrace_packet_t *packet);

#endif /* PROCESS_PKTGEN_H */
