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
#include <string.h>
#include <netinet/in.h>

#define TRUE            1
#define FALSE           0
#define PKTGEN_MAGIC    0xBE9BE955

typedef struct ll_stat_node {
    // Source address string
    char source_addr[20];

    // Count of total packets
    uint32_t total_packets;
    // Count of total packets out of order
    uint32_t total_out_order;
    // Count of total packets lost
    uint32_t total_lost;

    // Linked list that contains list nodes (carried forward for all iterations).
    struct ll_lost_node *lost;

    // Total travel time of packets in microseconds
    double total_time_micro;
    // Count of packets added to total time
    uint32_t total_time_count;

    // The current group that the aggregate stats belong to (groups of packets)
    uint32_t agg_group;

    // Timestamp of first packet in aggregation group
    struct timeval first_tv;
    // Timestamp of last packet in aggregation group
    struct timeval last_tv;

    /* ------ Last seen packet attributes  ------ */
    // Last sequence seen
    uint32_t last_seq;

    /* ------ Sequence number reset helpter attributes ------ */
    // Sequence reset start and end of range that needs to be removed
    uint32_t seqres_gp_start;
    uint32_t seqres_gp_end;
    // Perform sequence reset at the start of this group
    uint32_t seqres_on_gp;
    // Sequence reset operation needs to be performed
    uint32_t seqres_required;

    /* ------ Linked list attributes ------ */
    // Pointer to the next element in the list
    struct ll_stat_node *next;
} stat_node;


typedef struct ll_lost_node {
    // Start of sequence gap of lost packets (seen packet)
    uint32_t start;

    // End of the sequence gap of lost packets (seen packet)
    uint32_t end;

    // Group that the lost packet sequence belongs to
    // XXX: If we do thos then we need to make a new entry for missing
    // that are not part of same group. This could work assuming that a
    // packet is unique to a specific group, i.e. we can't have it go
    // missing twice. For now just ignore this. TODO
    uint32_t agg_group;

    // Pointer to the next element in the list
    struct ll_lost_node *next;
} lost_node;


/* -------------------- METHOD PROTOTYPES ------------------- */

// Usefull functions
static bool isPktgen(uint32_t *data, uint32_t *seq, struct timeval *tv);

static char *timeval_to_str(struct timeval *tv);

// Processing and aggregation methods
static void process_packet(libtrace_packet_t *packet, uint32_t groupSize);

// Add a packet to the stats list
static void add_stats(char *source_addr, uint32_t pktgen_seq, struct timeval *tv,
                                                struct timeval *pktgen_tv, uint32_t groupSize);

// Generate aggregate statitics of a stats node
static void aggregate_stats(stat_node *node);

// Insert the lost packet into the lost list
static void packet_lost(stat_node *stat, uint32_t pktgen_seq);

// Check if we have found a lost packet
static bool lost_packet_found(stat_node *stat, uint32_t pktgen_seq);

// Remove lost ranges under a specific aggregate group number
static void remove_lost_range(stat_node *stat, uint32_t start, uint32_t end);

// Output the contents of the lost list
static void dump_lost_list(stat_node *stat);

// Cleanup methods
static void cleanUpStats();

// Clean up a list of lost packets from a stats node
static void cleanUpLostList(stat_node *stat);

// Clean up the libtrace allocated resources
static void cleanUp(libtrace_t *trace, libtrace_packet_t *packet);

#endif /* PROCESS_PKTGEN_H */
