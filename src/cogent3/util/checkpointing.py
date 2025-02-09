#!/usr/bin/env python
import os
import pickle
import time


__author__ = ["Peter Maxwell", "Gavin Huttley"]
__copyright__ = "Copyright 2007-2019, The Cogent Project"
__credits__ = ["Peter Maxwell", "Gavin Huttley"]
__license__ = "BSD-3"
__version__ = "2019.9.13a"
__maintainer__ = "Gavin Huttley"
__email__ = "Gavin.Huttley@anu.edu.au"
__status__ = "Production"


class Checkpointer(object):
    def __init__(self, filename, interval=None, noisy=True):
        if interval is None:
            interval = 1800
        self.filename = filename
        self.interval = interval
        self.last_time = time.time()
        self.noisy = noisy

    def available(self):
        return self.filename is not None and os.path.exists(self.filename)

    def load(self):
        assert self.filename is not None, "check .available() first"
        print("RESUMING from file '%s'" % self.filename)
        with open(self.filename, "rb") as f:
            obj = pickle.load(f)
        self.last_time = time.time()
        return obj

    def record(self, obj, msg=None, always=False):
        if self.filename is None:
            return
        now = time.time()
        elapsed = now - self.last_time
        if always or elapsed > self.interval:
            if self.noisy:
                print("CHECKPOINTING to file '%s'" % self.filename)
                if msg is not None:
                    print(msg)
            with open(self.filename, "wb") as f:
                pickle.dump(obj, f)
            self.last_time = now
