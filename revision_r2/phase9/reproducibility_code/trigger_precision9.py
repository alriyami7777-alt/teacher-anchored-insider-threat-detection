from common9 import *
from prepare9 import trigger
def trigger_precise(raw):
 z=raw.copy();z[:,-3:,0:6]=np.rint(z[:,-3:,0:6]);return trigger(z)
