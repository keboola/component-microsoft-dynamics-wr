import logging
import sys
from dynamics.component import DynamicsComponent

sys.tracebacklimit = 0

if __name__ == '__main__':

    c = DynamicsComponent()
    c.run()

    logging.info("Writing finished.")
