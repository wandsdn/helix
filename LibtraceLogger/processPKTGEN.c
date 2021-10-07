/*
    Process pktgen traces application. This app processes two trace files
    and extracts from it recovery time. Please refer to main for a more
    detailed expalanation of the application functionality.
*/

#include "processPKTGEN.h"


uint32_t prim_pktgen_seq = 0;           /* Primary packet pktgen sequence */
struct timeval prim_pktgen_tv;          /* Prumary packet pktgen timestamp */
uint32_t sec_pktgen_seq = 0;            /* Secondary packet pktgen sequence */
struct timeval sec_pktgen_tv;           /* Secondary packet pktgen timestamp */


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
    Process a packet from the secondary trace. Method checks if the current
    packet is a pktgen. If it is we will save its pktgen sequence and
    timestamp in the global variables

    Args:
        packet: packet to process

    Returns:
        TRUE if pktgen packet found, FALSE otherwise
*/
static bool processSecondary(libtrace_packet_t *packet) {
    uint8_t  proto;
    uint32_t remaining;
    void *transportHeader;
    void *udpPayload;

    uint32_t pktgen_seq;
    struct timeval tv;

    /* Get transport header and validate its UDP packet */
    transportHeader = trace_get_transport(packet, &proto, &remaining);
    if (transportHeader == NULL)
        return FALSE;
    if (proto != TRACE_IPPROTO_UDP)
        return FALSE;

    /* Check that we have a complete UDP header */
    if (remaining < sizeof(libtrace_udp_t))
        return FALSE;

    /* Get the pktgen packet data and make sure its complete */
    udpPayload = trace_get_payload_from_udp(
            (libtrace_udp_t *)transportHeader, &remaining);
    if (remaining < 20)
        return FALSE;

    /* Validate the pktgen data */
    if (isPktgen((uint32_t *)udpPayload, &pktgen_seq, &tv) == FALSE)
        return FALSE;

    /* Save the pktgen details and return TRUE (found pktgen packet) */
    sec_pktgen_seq = pktgen_seq;
    sec_pktgen_tv = tv;
    return TRUE;
}


/*
    Process a packet from the primary trace. Method checks if we have found
    the last packet in the primary trace. If the current packet is a pktgen
    packet, we will check if its sequence number is larger than the global
    primary sequene variable. If it is we will save the pktgen timestamp
    and sequence to the global variables.

    Args:
        packet: packet to process
*/
static void processPrimary(libtrace_packet_t *packet) {
    uint8_t  proto;
    uint32_t remaining;
    void *transportHeader;
    void *udpPayload;

    uint32_t pktgen_seq;
    struct timeval tv;

    /* Get transport header and validate its UDP packet */
    transportHeader = trace_get_transport(packet, &proto, &remaining);
    if (transportHeader == NULL)
        return;
    if (proto != TRACE_IPPROTO_UDP)
        return;

    /* Check that we have a complete UDP header */
    if (remaining < sizeof(libtrace_udp_t))
        return;

    /* Get the pktgen packet data and make sure its complete */
    udpPayload = trace_get_payload_from_udp(
            (libtrace_udp_t *)transportHeader, &remaining);
    if (remaining < 20)
        return;

    /* Validate the pktgen data */
    if (isPktgen((uint32_t *)udpPayload, &pktgen_seq, &tv) == FALSE)
        return;

    /* Check if we have found the last packet in the primary trace */
    if (pktgen_seq > prim_pktgen_seq) {
        prim_pktgen_seq = pktgen_seq;
        prim_pktgen_tv = tv;
    }
}

/*
    Clean up the application by destroying the libtrace packes and
    traces

    Args:
        prim_trace: pointer to the primary trace
        sec_trace: pointer to the secondary trace
        packet: pointer to the libtrace packet used
*/
static void cleanUp(libtrace_t *prim_trace, libtrace_t *sec_trace,
             libtrace_packet_t *packet) {
    if (prim_trace)
        trace_destroy(prim_trace);
    if (sec_trace)
        trace_destroy(sec_trace);
    if (packet)
        trace_destroy_packet(packet);
}

/*
    Main method that initiates the processing. The application will
    use two traces (primary and secondary). It will find the first pktgen
    packet on the secondary trace (PF2) and then locate the last packet in
    the primary trace (PF1). The recover time is the difference in the
    two timestamps (PF2_Time - PF1_Time).

    Errors are written to standard out and have the format: ERROR!,Message.

    USAGE: primaryURI secondaryURI
        primaryURI - URI to trace to use as primary
        secondaryURI - URI to trace to use as secondary

    CONSOLE OUTPUT: (CSV, all on one line):
        PKTGEN_REC_TIME, TRACE_REC_TIME, LOST_PACKETS,
        PF1_PKTGEN_TIME, PF1_PKTGEN_SEQ, PF1_TRACE_TIME,
        PF2_PKTGEN_TIME, PF2_PKTGEN_SEQ, PF2_TRACE_TIME
*/
int main(int argc, char *argv[]) {
    libtrace_t *prim_trace = NULL;
    libtrace_t *sec_trace = NULL;
    libtrace_packet_t *packet = NULL;

    /* Check arguments */
    if (argc < 3) {
        fprintf(stderr, "USAGE: %s primaryURI secondaryURI\n", argv[0]);
        return 1;
    }

    /* Initiate the packet structure used to traverse */
    packet = trace_create_packet();
    if (packet == NULL) {
        perror("Creating libtrace packet");
        cleanUp(prim_trace, sec_trace, packet);
        return -1;
    }

    /* Initiate the secondary trace  */
    sec_trace = trace_create(argv[2]);
    if (trace_is_err(sec_trace)) {
        trace_perror(sec_trace, "Error opening secondary trace");
        cleanUp(prim_trace, sec_trace, packet);
        return -1;
    }

    if (trace_start(sec_trace) == -1) {
        trace_perror(sec_trace, "Error starting secondary trace");
        cleanUp(prim_trace, sec_trace, packet);
        return -1;
    }

    /* Read the secondary trace and locate the first pktgen packet */
    while (trace_read_packet(sec_trace, packet) > 0) {
        if (processSecondary(packet) == TRUE)
            break;
    }

    /* Check if trace encountered error and validate we have located PKTGEN packet */
    if (trace_is_err(sec_trace)) {
        trace_perror(sec_trace, "Error reading packets from secondary");
        cleanUp(prim_trace, sec_trace, packet);
        return -1;
    }

    if (sec_pktgen_seq == 0) {
        printf("Error!,Can't locate PKTGEN packet in secondary trace %s", argv[2]);
        cleanUp(prim_trace, sec_trace, packet);
        return -1;
    }

    /* Close the secondary trace */
    trace_destroy(sec_trace);
    sec_trace = NULL;

    /* Initiate the primary trace */
    prim_trace = trace_create(argv[1]);
    if (trace_is_err(prim_trace)) {
        trace_perror(prim_trace, "Error opening primary trace");
        cleanUp(prim_trace, sec_trace, packet);
        return -1;
    }

    if (trace_start(prim_trace) == -1) {
        trace_perror(prim_trace, "Error starting primary trace");
        cleanUp(prim_trace, sec_trace, packet);
        return -1;
    }

    /* Go through the primary trace and find the last pktgen packet */
    while (trace_read_packet(prim_trace, packet) > 0) {
        processPrimary(packet);
    }

    /* Check if trace encountered error and make sure we have found a PKTGEN packet */
    if (trace_is_err(prim_trace)) {
        trace_perror(prim_trace, "Error reading packets from primary");
        cleanUp(prim_trace, sec_trace, packet);
        return -1;
    }

    if (prim_pktgen_seq == 0) {
        printf("Error!,Can't locate PKTGEN packet in primary trace %s", argv[2]);
        cleanUp(prim_trace, sec_trace, packet);
        return -1;
    }

    /* Calculate the recovery time */
    int32_t rec_time = (sec_pktgen_tv.tv_sec - prim_pktgen_tv.tv_sec) * 1000000;
    rec_time += sec_pktgen_tv.tv_usec - prim_pktgen_tv.tv_usec;
    double rec_time_ms = ((double)rec_time) / 1000.0d;

    /* Calculate the number of lost packets */
    int32_t packet_loss = sec_pktgen_seq - prim_pktgen_seq;

    /* Print the recovery time results */
    char *prim_pktgen_t =  timeval_to_str(&prim_pktgen_tv);
    char *sec_pktgen_t = timeval_to_str(&sec_pktgen_tv);
    printf("%f,%d,%lu,%s,%lu,%s", rec_time_ms, (int)packet_loss,
                (unsigned long)prim_pktgen_seq, prim_pktgen_t,
                (unsigned long)sec_pktgen_seq, sec_pktgen_t);

    /* Free the timestamp pointers */
    free(prim_pktgen_t);
    free(sec_pktgen_t);

    /* Cleanup and exit the app */
    cleanUp(prim_trace, sec_trace, packet);
    return 0;
}
