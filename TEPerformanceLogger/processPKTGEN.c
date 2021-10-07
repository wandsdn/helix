/*
    Process pktgen traces applicatiom. App will process a trace file and
    extract from it TE performance statistics which look at the delay between
    packets and also any re-ordering or losses that occur.
*/

#include "processPKTGEN.h"
#include "reorder_list.c"

// Pointer to the stats list
stat_node *stats;


/*
    Check if a specific payload of data contains a pktgen packet. If
    data contains a pktgen packet, seq and tv will be overwritten
    with the pktgen packet values (passed by reference). If no pktgen
    packet found seq and tv are not modified. We match pktgen packets based
    on the 4 byte magic.

    Args:
        data: data of packet to check
        seq: pointer to a var to save pktgen seq in host byte order
        tv: pointer to a var to save pktgen timestamp

    Returns:
        TRUE if data contains a pktgen packet, FALSE otherwise.
*/
static bool isPktgen(uint32_t *data, uint32_t *seq, struct timeval *tv) {
    /* Validate that we have data to process */
    if (data == NULL)
        return FALSE;

    /* Extract the magic (convert byte order) */
    uint32_t magic = ntohl(data[0]);

    /* If magic matches pktgen extract pktgen fields. */
    if (magic == PKTGEN_MAGIC) {
        *seq = ntohl(data[1]);
        tv->tv_sec = ntohl(data[2]);
        tv->tv_usec = ntohl(data[3]);
        return TRUE;
    }

    return FALSE;
}


/*
    Convert a timeval structure to a human readable timestamp.
    The foramt of the timestamp is YYYY-MM-DD HH:MM:SS.ZZZZZZ.

    Args:
        tv: timeval to convert to a human readable timestamp

    Returns:
        Pointer to converted string. FREE POINTER ONCE DONE!
*/
static char *timeval_to_str(struct timeval *tv) {
    /* Initiate our buffers to store the conversion and results*/
    char *res = (char *)malloc(30);
    char buf[30];

    /* Extract the tvsec part of the timestamp and convert to string */
    time_t time = tv->tv_sec;
    struct tm tm_time = *localtime(&time);
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tm_time);

    /* Add the miliseconds to the timestamp and prepare the result */
    snprintf(res, 30, "%s.%06ld", buf, tv->tv_usec);
    return res;
}


/*
    Process packet and add its information to the stats list if it's a PKTGEN
    packet.

    Args:
        packet: packet to process
        groupSize: number of packets to aggregate before outputing stats
*/
static void process_packet(libtrace_packet_t *packet, uint32_t groupSize) {
    uint8_t  proto;
    uint32_t remaining;
    void *transportHeader;
    void *udpPayload;

    // Packet detils
    uint32_t pktgen_seq;
    struct timeval tv;
    struct timeval pktgen_tv;
    char source_addr[20];

    // Get the source address and arival time of the packet
    if (trace_get_source_address_string(packet, &source_addr[0], sizeof(source_addr)) == NULL)
        return;

    tv = trace_get_timeval(packet);

    // Validate packet is UDP and make sure we have a complete header
    transportHeader = trace_get_transport(packet, &proto, &remaining);
    if (transportHeader == NULL)
        return;
    if (proto != TRACE_IPPROTO_UDP)
        return;
    if (remaining < sizeof(libtrace_udp_t))
        return;

    // Retrieve the packet data and check if its a PKTGEN  packet
    udpPayload = trace_get_payload_from_udp(
            (libtrace_udp_t *)transportHeader, &remaining);
    if (remaining < 20)
        return;
    if (isPktgen((uint32_t *)udpPayload, &pktgen_seq, &pktgen_tv) == FALSE)
        return;

    // Add the packet info the stats list
    add_stats(&source_addr[0], pktgen_seq, &tv, &pktgen_tv, groupSize);
}


/*
    Add packet information to the aggregate statistics. This method will output the aggregate
    stats for a stream if groupSize packets have been collected.

    Args:
        source_addr: Pktgen packet source address to identify stream
        pktgen_seq: Pktgen sequence number
        tv: Arrival time of the packet
        pktgen_tv: Pktgen timestamp of the packet to compute trip time
        groupSize: Number of packets to aggregate before outputing stats
*/
static void add_stats(char *source_addr, uint32_t pktgen_seq, struct timeval *tv,
                                            struct timeval *pktgen_tv, uint32_t groupSize) {
    stat_node *iter = stats;
    stat_node *node = NULL;

    // Traverse the stats list until we find the flow
    while (iter != NULL) {
        // If we already have an entry for the stats
        if (strcmp(source_addr, iter->source_addr) == 0) {
            node = iter;
            break;
        } else if (iter->next == NULL) {
            // We have found the final element in the list so just exit
            break;
        } else {
            // Go to the next element in list to find the item
            iter = iter->next;
        }
    }

    // Compute the time it took the packet to traverl through the network in microseconds
    double diff_micro = (tv->tv_sec - pktgen_tv->tv_sec) * 1000000;
    diff_micro += (tv->tv_usec - pktgen_tv->tv_usec);

    // If we couldn't find a node in the stats list create a new one
    if (node == NULL) {
        // Allocate a new node
        node = (stat_node *) malloc(sizeof (stat_node));
        if (node == NULL) {
            // We have ran out of memeory, exit and kill everything
            return;
        }

        // Set the new nodes values
        strcpy(&node->source_addr[0], source_addr);
        node->total_packets = 1;
        node->total_out_order = 0;
        node->total_lost = 0;
        node->total_time_micro = diff_micro;
        node->total_time_count = 1;
        node->agg_group = 0;

        node->last_seq = pktgen_seq;
        node->lost = NULL;
        node->next = NULL;
        node->first_tv.tv_sec = tv->tv_sec;
        node->first_tv.tv_usec = tv->tv_usec;
        node->last_tv.tv_sec = tv->tv_sec;
        node->last_tv.tv_usec = tv->tv_usec;
        node->seqres_required = FALSE;

        // Add the packet to the stats list
        if (iter == NULL) {
            // This is the special case to deal with an empty list
            stats = node;
        } else {
            // Append the new address to the list
            iter->next = node;
        }

        // If the first packet is not number 1 in sequence add to lost list
        //printf("HEAD MADE %s %u\n", source_addr, pktgen_seq);
        if (pktgen_seq != 1) {
            node->last_seq = 0;
            packet_lost(node, pktgen_seq);
            node->last_seq = pktgen_seq;
        }
    } else {
        // XXX: If the current packet wrapped around the aggregate stats and reset
        if (node->last_seq > groupSize && pktgen_seq == 1) {
            printf("STATS WRAPPED %s %u %u\n", source_addr, node->last_seq, pktgen_seq);
            aggregate_stats(node);

            // Remove all lost ranges that are very outstanding (as we reset sequneces)
            printf("Removed lost range %u-%u of %s\n", 0, node->agg_group - 2, node->source_addr);
            remove_lost_range(node, 0, node->agg_group - 2);

            // Ovewrite the node value
            strcpy(&node->source_addr[0], source_addr);
            node->total_packets = 1;
            node->total_out_order = 0;
            node->total_lost = 0;
            node->total_time_micro = diff_micro;
            node->total_time_count = 1;
            node->last_seq = pktgen_seq;
            node->first_tv.tv_sec = tv->tv_sec;
            node->first_tv.tv_usec = tv->tv_usec;
            node->last_tv.tv_sec = tv->tv_sec;
            node->last_tv.tv_usec = tv->tv_usec;

            // Schedule clearing of the old lost sequence on the next aggregation
            node->seqres_gp_start = node->agg_group - 1;
            node->seqres_gp_end = node->agg_group - 1;
            node->seqres_on_gp = node->agg_group + 1;
            node->seqres_required = TRUE;
            printf("Scheduled seq reset lost range %u-%u on group start %u for %s\n",
                node->seqres_gp_start, node->seqres_gp_end, node->seqres_on_gp, node->source_addr);
            return;
        }

        // Increment packets we have seen and total time count
        node->total_packets += 1;
        node->total_time_micro += diff_micro;
        node->total_time_count += 1;
        node->last_tv.tv_sec = tv->tv_sec;
        node->last_tv.tv_usec = tv->tv_usec;

        // Check if this is a lost packet we have found
        if (lost_packet_found(node, pktgen_seq) == TRUE) {
//            printf("FOUND LOST PACKET %u %s\n", pktgen_seq, source_addr);
            node->total_out_order += 1;
//            dump_lost_list(node);
        } else {
            // Check if this is a lost packet
            if ((node->last_seq + 1) != pktgen_seq) {
//                printf("PRRESUME_LOST: %s %u %u \n", source_addr, pktgen_seq, node->last_seq);
                packet_lost(node, pktgen_seq);
//                dump_lost_list(node);
            }

            // Update the last seen sequence (packet in order)
            node->last_seq = pktgen_seq;
        }

        // Check if we have reached the aggregate group size and output stats
        // XXX: Should we only do this when we get an in-order packet, i.e. what we expect?
        if (node->total_packets == groupSize) {
            aggregate_stats(node);
            node->first_tv.tv_sec = tv->tv_sec;
            node->first_tv.tv_usec = tv->tv_usec;
        }
    }
}


/*
    Compute and output the aggregate stats for a specific stats list node.

    Args:
        node: stat node to output and compute aggregate stats for
*/
static void aggregate_stats(stat_node *node) {
    // Compute the averages for the stats
    double avg_time_micro = (node->total_time_micro / ((double) node->total_time_count));
    double per_ord = (((double)node->total_out_order) / ((double)node->total_packets)) * 100.0d;

    // Work out the number of lost packets for the current grup
    uint32_t lost = 0;
    lost_node *iter = node->lost;
    while (iter != NULL) {
        if (iter->agg_group == node->agg_group) {
            lost += ((iter->end - iter->start) + 1);
        }
        iter = iter->next;
    }
    double per_lost = (((double)lost) / ((double)node->total_packets)) * 100.0d;

    // Compute the group time in micro seconds
    double gtime_ms = (node->last_tv.tv_sec - node->first_tv.tv_sec) * 1000000;
    gtime_ms += (node->last_tv.tv_usec - node->first_tv.tv_usec);
    gtime_ms = gtime_ms / 1000.0d;

    // Output the average stats
    printf("%s\t%u\t%u\t%.2f\t%.2f\t%u\t%.2f\t%u\t%.2f\t%.2f\n", node->source_addr,
            node->agg_group, node->total_packets, node->total_time_micro, avg_time_micro,
            lost, per_lost, node->total_out_order, per_ord, gtime_ms);

    // Reset the aggregated stat that we have processed
    node->total_packets = 0;
    node->total_out_order = 0;
    node->total_lost = 0;
    node->total_time_micro = 0;
    node->total_time_count = 0;
    node->agg_group += 1;

    // Clear any lost list elements if required
    if ((node->seqres_required == TRUE) && (node->seqres_on_gp == node->agg_group)) {
        printf("Doing seq res on lost range %u-%u on group start %u for %s\n", node->seqres_gp_start,
            node->seqres_gp_end, node->seqres_on_gp, node->source_addr);
        remove_lost_range(node, node->seqres_gp_start, node->seqres_gp_end);
        node->seqres_required = FALSE;
    }
}



/*
    Check if we have found a lost packet by iterting through the lost list and
    checking if the sequence number is within a lost packet range. If a lost packet
    is found the lost list will be modified to reflect this.

    Args:
        stat: stat node to check if lost packet was found
        pktgen_seq: sequence number of the packet

    Returns:
        TRUE if we found a lost packet, FALSE otherwise
*/
static bool lost_packet_found(stat_node *stat, uint32_t pktgen_seq) {
    // There are no lost packets
    if (stat->lost == NULL)
        return FALSE;

    // Iterate through list of lost packets and see if we found a lost packet
    lost_node *iter = stat->lost;
    lost_node *prev = NULL;
    while (iter != NULL) {
        if ((iter->start <= pktgen_seq) && (iter->end >= pktgen_seq)) {
            // Check if the packet is for an old group
            if (stat->agg_group != iter->agg_group) {
                add_reorder(stat->source_addr, iter->agg_group);
            }

            // Found a lost packet check if we need to remove the start
            if ((iter->start == pktgen_seq) && (iter->end == pktgen_seq)) {
                // If the node has one element, lost packet, remove node
                if (prev == NULL) {
                    // Head modification
                    stat->lost = iter->next;
                } else {
                    prev->next = iter->next;
                }

                free(iter);
                return TRUE;
            } else if (iter->start == pktgen_seq) {
                // Remove from start of range
                iter->start = pktgen_seq + 1;
                return TRUE;
            } else if (iter->start == pktgen_seq) {
                // Remove from end of range
                iter->end = pktgen_seq -1;
                return TRUE;
            } else {
                // Split the range
                lost_node *new_node = (lost_node *) malloc(sizeof (lost_node));
                if (new_node == NULL) {
                    return FALSE;
                }

                new_node->start = pktgen_seq + 1;
                new_node->end = iter->end;
                new_node->agg_group = iter->agg_group;
                new_node->next = iter->next;
                iter->end = pktgen_seq - 1;
                iter->next = new_node;
                return TRUE;
            }
        }

        // Go to next node in list
        prev = iter;
        iter = iter->next;
    }

    return FALSE;
}


/*
    Remove lost packet ranges that are within a group range.

    Args:
        stat: Stat node to remove lost packets from
        start: Start of the search range
        end: End of the search range
*/
static void remove_lost_range(stat_node *stat, uint32_t start, uint32_t end) {
    lost_node *iter = stat->lost;
    lost_node *prev = NULL;
    while (iter != NULL) {
        // Check if the stat is within the search range
        if ((iter->agg_group >= start) && (iter->agg_group <= end)) {
            // Remove from the head of the list
            if (prev == NULL) {
                stat->lost = iter->next;
                free(iter);
                iter = stat->lost;
                continue;
            }

            // Remove a node
            prev->next = iter->next;
            free(iter);
            iter = prev->next;
            continue;
        }

        // Go to next element in list
        prev = iter;
        iter = iter->next;
    }
}


/*
    Add a lost packet sequence range to the list of lost packets. Method will merge
    adjacent nodes if there is no gap between them. The aggregate group number is
    used to figure out if we can merge list nodes. Range is defined as <last packet
    sequence number +1> to <packet sequence - 1>.

    Note: nodes will be added to the list in order, however, if the group is different
    new groups are added to the end of the list.

    TODO: Method dosen't currently merge adjacent ranges !!!

    Args:
        stat: Stat node to add lost packet
        pktgen_seq: Sequence number of lost packet
*/
static void packet_lost(stat_node *stat, uint32_t pktgen_seq) {
    uint32_t lost_start = stat->last_seq + 1;
    uint32_t lost_end = pktgen_seq - 1;

    // FIXME: This is clearly a wrap around issue, so we can ignore any lost
    // packets ... really strange scenario, need to find a better way to
    // fix this.
    if ((lost_end - lost_start) > 10000) {
        printf("Lost 10,000 packets %s %u %u!\n", stat->source_addr, lost_start, lost_end);
        return;
    }

    // Special case: empty lost list
    if (stat->lost == NULL) {
        lost_node *new_node = (lost_node *) malloc(sizeof (lost_node));
        if (new_node == NULL) {
            printf("NO MORE MEMEORY\n");
            return;
        }

        new_node->start = lost_start;
        new_node->end = lost_end;
        new_node->next = NULL;
        new_node->agg_group = stat->agg_group;
        stat->lost = new_node;
        return;
    }

    // Traverse the lost list until we figure out where to insert it
    lost_node *prev = NULL;
    lost_node *iter = stat->lost;
    while (iter != NULL) {
        // Insert packet at head of list
        if ((iter->start > lost_end) && (iter->agg_group == stat->agg_group)) {
            lost_node *new_node = (lost_node *) malloc(sizeof (lost_node));
            if (new_node == NULL) {
                return;
            }

            new_node->start = lost_start;
            new_node->end = lost_end;
            new_node->next = iter->next;
            new_node->agg_group = stat->agg_group;
            if (prev == NULL) {
                // Special case insert at the head
                stat->lost = new_node;
                return;
            }

            prev->next = new_node;
            return;
        }

        // Go to next node in list
        prev = iter;
        iter = iter->next;
    }

    // Our range is grater than all packets in list, added to end of list
    lost_node *new_node = (lost_node *) malloc(sizeof (lost_node));
    if (new_node == NULL) {
        return;
    }
    new_node->start = lost_start;
    new_node->end = lost_end;
    new_node->next = iter;
    new_node->agg_group = stat->agg_group;
    prev->next = new_node;
}


/*
    Dump the contents of the lost list on screen

    Args:
        stat: Dump lost list of this stat node
*/
static void dump_lost_list(stat_node *stat) {
    lost_node *iter = stat->lost;
    printf("LOST LIST: ");
    while (iter != NULL) {
        printf("%u-%u(%u) ", iter->start, iter->end, iter->agg_group);
        iter = iter->next;
    }
    printf("\n\n");
}


/*
    Free the allocated stats list and and reorder list
*/
static void cleanUpStats() {
    stat_node *iter = stats;
    stat_node *next = NULL;

    while (iter != NULL) {
        // Free the lost list
        cleanUpLostList(iter);

        // Free the stat list and move on
        next = iter->next;
        free(iter);
        iter = next;
    }

    // Free the re-order list
    clear_reorder();
}

/*
    Free an allocated lost list and sub elements
*/
static void cleanUpLostList(stat_node *stat) {
    lost_node *iter = stat->lost;
    lost_node *next = NULL;

    while (iter != NULL) {
        next = iter->next;
        free(iter);
        iter = next;
    }

    stat->lost = NULL;
}

/*
    Clean up the application by destroying the libtrace packes and
    traces

    Args:
        trace: pointer to the trace file
        packet: pointer to the libtrace packet used
*/
static void cleanUp(libtrace_t *trace, libtrace_packet_t *packet) {
    if (trace)
        trace_destroy(trace);
    if (packet)
        trace_destroy_packet(packet);
}


/*
    Main method that initiates the processing. The application will iterate
    through a pcap file, processing pktgen streams and output aggregate stats
    such as lattency time or packet loss to standard out.

    Errors are written to standard out and have the format: ERROR!,Message.

    USAGE: inputURI [groupSize]
        inputURI - URI of trace
        groupSize - Number packets in a output group. Defaults to 10,000

    CONSOLE OUTPUT: (CSV, all on one line):
        ...
*/
int main(int argc, char *argv[]) {
    libtrace_t *trace = NULL;
    libtrace_packet_t *packet = NULL;

    // Reset the global variables pointers of the linked lists to NULL
    reorder_list = NULL;
    stats = NULL;

    // Check arguments
    if (argc < 2) {
        fprintf(stderr, "USAGE: %s inputURI [groupSize]\n", argv[0]);
        return 1;
    }

    // Check if group size was specified
    uint32_t groupSize = 10000;
    if (argc > 2) {
        groupSize = atoi(argv[2]);
    }

    // Initiate the packet structure used to traverse
    packet = trace_create_packet();
    if (packet == NULL) {
        perror("Creating libtrace packet");
        cleanUp(trace, packet);
        return -1;
    }

    // Initiate the trace
    trace = trace_create(argv[1]);
    if (trace_is_err(trace)) {
        trace_perror(trace, "Error opening trace");
        cleanUp(trace, packet);
        return -1;
    }

    if (trace_start(trace) == -1) {
        trace_perror(trace, "Error starting trace");
        cleanUp(trace, packet);
        return -1;
    }

    // Iterate through the trace and process the packets into the structs
    printf("Addres\tGroup\t# Packets\tTotal Time\tAvg Time\t# Lost\t%% Lost\t");
    printf("# Reoder\t%% Reoder\tGroup Time\n");
    while (trace_read_packet(trace, packet) > 0) {
        process_packet(packet, groupSize);
    }

    // Process the final left over stats, if there are any
    stat_node *iter = stats;
    while (iter != NULL) {
        aggregate_stats(iter);
        iter = iter->next;
    }

    /* Check if trace encountered error and validate we have located PKTGEN packet */
    if (trace_is_err(trace)) {
        trace_perror(trace, "Error reading packets from trace");
        cleanUp(trace, packet);
        cleanUpStats();
        return -1;
    }

    // Cleanup and exit the app
    dump_reorder();
    cleanUp(trace, packet);
    cleanUpStats();
    return 0;
}
