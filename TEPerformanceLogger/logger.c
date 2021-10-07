/*
    Log pktgen packets from a input stream to a output libtrace stream. The
    catpure can be limited to a certain number of packets or ran indefinetly.
    Please refer to the main method for a full description of the arguments.
*/
#include "logger.h"


/* Number of pktgen packets we have processed */
static uint8_t pktgen_count = 0;
/* Flag that indicates if we need to stop the packet capture */
static bool stop_capture = FALSE;

/* Trace variables */
static libtrace_t *trace = NULL;
static libtrace_packet_t *packet = NULL;
static libtrace_filter_t *filter = NULL;
static libtrace_out_t *out = NULL;


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
    Process a UDP packet and check if it contains a pktgen packet
    in its payload.

    Returns:
        -1 if an error has occured writing to output, 0 otherwise.
*/
static int processPacket() {
    uint8_t  proto;
    uint32_t remaining;
    void *transportHeader;
    void *udpPayload;

    uint32_t pktgen_seq;
    struct timeval tv;

    /* Get transport header and validate its UDP packet */
    transportHeader = trace_get_transport(packet, &proto, &remaining);
    if (transportHeader == NULL)
        return 0;
    if (proto != TRACE_IPPROTO_UDP)
        return 0;

    /* Check that we have a complete UDP header */
    if (remaining < sizeof(libtrace_udp_t))
        return 0;

    /* Get the pktgen packet data and make sure its complete */
    udpPayload = trace_get_payload_from_udp(
            (libtrace_udp_t *)transportHeader, &remaining);
    if (remaining < 20)
        return 0;

    /* Validate the pktgen data */
    if (isPktgen((uint32_t *)udpPayload, &pktgen_seq, &tv) == FALSE)
        return 0;

    /* Save packet to out trace */
    if (trace_write_packet(out, packet) == -1)
        return -1;

    pktgen_count ++;
    return 0;
}

/*
    Clean up the application by destroying the libtrace packet, filter and
    traces objects.

    Args:
        trace: pointer to a libtrace trace to be freed
        packet: pointer to a libtrace packet to be freed
        filter: pointer to libtrace filter to be freed
        out: pointer to libtrace output trace to be freed
*/
static void cleanUp() {
    if (trace)
        trace_destroy(trace);
    if (out)
        trace_destroy_output(out);
    if (packet)
        trace_destroy_packet(packet);
    if (filter)
        trace_destroy_filter(filter);
}

/*
    Signal handler that sets the stop packet capture app flag to stop processing
    the packet capture and cleanly exit the app.

    Args:
        sig - Signal that occured
*/
static void signalHandler(int sig) {
    stop_capture = TRUE;
}

/*
    Main method that initiates the processing.

    USAGE: inputURI outputURI <max count>
        inputURI - input URI to capture and check for pktgen packets
        outputURI - URI of location to save pktgen packets captured
        <max count> - Optional. Maximum number of packets to capture on interface.
        If a value less than 1 is provided we will capture indefinetly. Defaults to 0.

        Please note that when in indefinet capture mode the app will exit cleanly when
        it recives a SIGINT signal. After signaling the app, once all resources are fred
        DONE will be written to the logger.done file. THe logger.done file is only used
        when the app is placed in indefinet logging mode.

*/
int main(int argc, char *argv[]) {
    int max_count = 0;

    /* Check arguments and process them */
    if (argc < 3) {
        fprintf(stderr, "USAGE: %s inputURI outputURI <max count>\n", argv[0]);
        fprintf(stderr, "\tinputURI - URI for input trace (i.e. int:eth0)\n\n");
        fprintf(stderr, "\toutputURI - URI for output trace (i.e. pcap:test.pcap)\n\n");
        fprintf(stderr, "\t<max count> - Number of packets to capture\n");
        fprintf(stderr, "\t              If < 1 record until stopped\n");
        return 1;
    }

    if (argc > 3) {
        char *p;
        max_count = strtol(argv[3], &p, 10);
    }

    /* If we have to run indefinetly output the PID to a file */
    if (max_count < 1) {
        signal(SIGINT, signalHandler);
    }

    /* Initiate and start the output trace */
    out = trace_create_output(argv[2]);
    if (trace_is_err_output(out)) {
        trace_perror_output(out, "Error opening out trace");
        cleanUp();
        return -1;
    }

    if (trace_start_output(out) == -1) {
        trace_perror_output(out, "Error starting out trace");
        cleanUp();
        return -1;
    }

    /* Initiate the input trace */
    trace = trace_create(argv[1]);
    if (trace_is_err(trace)) {
        trace_perror(trace, "Error opening trace");
        cleanUp();
        return -1;
    }

    /* Initiate the libtrace packet and filter and start the in trace */
    packet = trace_create_packet();
    if (packet == NULL) {
        perror("Creating libtrace packet");
        cleanUp();
        return -1;
    }

    filter = trace_create_filter("udp");
    if (trace_config(trace, TRACE_OPTION_FILTER, filter) == -1) {
        trace_perror(trace, "Error applying filter");
        cleanUp();
        return -1;
    }

    if (trace_start(trace) == -1) {
        trace_perror(trace, "Error starting trace");
        cleanUp();
        return -1;
    }

    /* Read the packets from the trace */
    while (trace_read_packet(trace, packet) > 0) {
        if (processPacket(packet, out) == -1) {
            trace_perror_output(out, "Error saving packet to trace");
            cleanUp();
            return -1;
        }

        /* Check if we have reached caputre limit or if we need to stop */
        if (pktgen_count >= max_count && max_count > 0)
            break;
        if (stop_capture == TRUE)
            break;
    }

    /*
        Check if the trace processing terminated with an error
        XXX: Disabled as this will be triggered by taking intf down!
    */
    /*if (trace_is_err(trace)) {
        trace_perror(trace, "Error reading packets");
        cleanUp();
        return -1;
    }*/

    cleanUp();

    /* Flag that the app has exited if running in idefinet mode (once done)*/
    if (max_count < 1) {
        FILE *fp;
        fp = fopen("logger.done", "w");
        fprintf(fp, "DONE\n");
        fclose(fp);
    }

    return 0;
}
