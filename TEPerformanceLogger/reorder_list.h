#ifndef REORDER_LIST_H
#define REORDER_LIST_H

#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>


typedef struct ll_reorder_node {
    // Source address for the group
    char source_addr[20];

    // Reorder packets of the group, used for adjustment
    uint32_t agg_group;

    // Number arrived out of order
    uint32_t count;

    // Pointer to the next element in the list
    struct ll_reorder_node *next;
} reorder_node;


static void add_reorder(char *source_addr, uint32_t group);

static void dump_reorder();

static void clear_reorder();


#endif /* REORDER_LIST_H */
