/*
    Header file of the logger which contains all the includes used in the
    logger.c source file and defines all method prototypes. For more detailed
    description of each method functionality please refer to logger.c.
*/

#ifndef LOGGER_H
#define LOGGER_H

#include "libtrace.h"
#include <time.h>
#include <stdlib.h>

/* SIGNAL HANDLER */
#include <signal.h>

/* GET PID INCLUDE */
#include <unistd.h>

#define TRUE            1
#define FALSE           0
#define PKTGEN_MAGIC    0xBE9BE955


/* -------------------- METHOD PROTOTYPES ------------------- */


static bool isPktgen(uint32_t *data, uint32_t *seq, struct timeval *tv);

static int processPacket();

static void cleanUp();


#endif /* LOGGER_H */
