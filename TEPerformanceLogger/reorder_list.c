#include "reorder_list.h"

reorder_node *reorder_list;

/*
    Add a new out of order packet to the adjustment list.

    Args:
        source_addr: IP address of the stream the out of order packet belongs to
        group: Group that the out of order packet belongs to
*/
static void add_reorder(char *source_addr, uint32_t group) {
    // Specia calse, add a new node to the head of the list
    if (reorder_list == NULL) {
        reorder_node *new_node = (reorder_node *) malloc(sizeof(reorder_node));
        if (new_node == NULL) {
            return;
        }

        strcpy(&new_node->source_addr[0], source_addr);
        new_node->agg_group = group;
        new_node->count = 1;
        new_node->next = NULL;
        reorder_list = new_node;
        return;
    }

    // Check if the we already have a list entry for the out of order pacekt
    reorder_node *iter = reorder_list;
    reorder_node *prev = NULL;
    while (iter != NULL) {
        if ((strcmp(source_addr, iter->source_addr) == 0) && (iter->agg_group == group)) {
            iter->count += 1;
            return;
        }

        prev = iter;
        iter = iter->next;
    }

    // Add a new node to the end of the out of order list adjustment list
    reorder_node *new_node = (reorder_node *) malloc(sizeof(reorder_node));
    strcpy(&new_node->source_addr[0], source_addr);
    new_node->agg_group = group;
    new_node->count = 1;
    new_node->next = NULL;
    prev->next = new_node;
}


/*
    Output the contents of the out of order list.
*/
static void dump_reorder() {
    reorder_node *iter = reorder_list;
    printf("\nAddr\tGroup\t# Out Order\n");
    while (iter != NULL) {
        printf("%s\t%u\t%u\n", iter->source_addr, iter->agg_group, iter->count);
        iter = iter->next;
    }
}


/*
    Free the resources allocated to the out of order list
*/
static void clear_reorder() {
    reorder_node *iter = reorder_list;
    reorder_node *next = NULL;
    while (iter != NULL) {
        next = iter->next;
        free(iter);
        iter = next;
    }
}
