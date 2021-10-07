#!/usr/bin/python

""" Proactive controller alternative implementation which uses a protection based
recovery method to deal with link failure. This version of the proactive controller
will compute loose path splices. See ```ProactiveController.py``` for implementation.

Usage:
    ryu-manager ProactiveControllerAlt.py --observe-links
"""

from ProactiveController import ProactiveController


class ProactiveControllerAlt(ProactiveController):
    """ Ryu proactive controller alternative implementation. Controller will inherit
    all behaivour and operations from the standard proactive controller. Path
    splices will be computed as loose. A lose path splice extends the possible list
    of candidate path splice nodes resulting in more diverse path splices.

    Refer to ```ProactiveControllerAlt.py``` for more info.
    """
    LOOSE_SPLICE = True      # COMPUTE LOOSE PATH SPLICES


    def __init__(self, *args, **kwargs):
        super(ProactiveControllerAlt, self).__init__(*args, **kwargs)
