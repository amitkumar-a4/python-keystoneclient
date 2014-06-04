from datetime import datetime, timedelta
from math import ceil
from dateutil.parser import parse
import json

#from workloadmgr.apscheduler.util import convert_to_datetime, timedelta_seconds
from workloadmgr.apscheduler.util import *


class WorkloadMgrTrigger(object):
    def __init__(self, jobschedule):
        jobschedule = json.loads(jobschedule)
        self.start_date = datetime.now()
        self.end_date = None
        self.interval = timedelta(seconds=3600)

        if 'startdate' in jobschedule and jobschedule['startdate'].strip(" ").lower() != "now":
            self.start_date = convert_to_datetime(parse(jobschedule['startdate']))

        if 'enddate' in jobschedule and jobschedule['enddate'].strip(" ").lower() != "no end":
            self.end_date = convert_to_datetime(parse(jobschedule['enddate']))

        if 'interval' in jobschedule:
            if jobschedule['interval'].find("hr"):
               if int(jobschedule['interval'].strip(" ").split("hr")[0]) >= 1 and int(jobschedule['interval'].strip(" ").split("hr")[0]) <= 12:
                  self.interval = timedelta(hours= int(jobschedule['interval'].strip(" ").split("hr")[0]))
               else:
                  raise Exception("Invalid format in the job scheduler")


        # We put at least 30 min window between snapshots.
        # otherwise we will thrashing the production system
        if (self.interval < timedelta(seconds=1800)):
            self.interval = timedelta(seconds=1800)

        self.interval_length = timedelta_seconds(self.interval)
        self.schedule_now = False

    def get_next_fire_time(self, start_date):

        # Perhaps workload_snapshot asked to schedule the job
        # immediately

        #if self.schedule_now:
           #self.schedule_now = False
           #return start_date + timedelta(seconds=5)

        if self.end_date:
           if self.end_date < self.start_date:
              return None

        if start_date < self.start_date:
            return self.start_date

        if self.end_date and start_date > self.end_date:
            return None

        timediff_seconds = timedelta_seconds(start_date - self.start_date)
        next_interval_num = int(ceil(timediff_seconds / self.interval_length))
        return self.start_date + self.interval * next_interval_num

    def __str__(self):
        return 'startdate[%s] enddate[%s] interval[%s]' % (str(self.start_date), str(self.end_date), str(self.interval))

    def __repr__(self):
        return "<%s (interval=%s, start_date=%s end_date=%s)>" % (
            self.__class__.__name__, repr(self.interval),
            repr(self.start_date), repr(self.end_date))

"""
#Unit Tests
import pdb;pdb.set_trace()
trigger = WorkloadMgrTrigger(u'{"startdate":"Now","enddate":"No End","starttime":"12:00am","interval":"1 hr","snapshotstokeep":"10"}')
print trigger
print trigger.get_next_fire_time(datetime.now())
print trigger.get_next_fire_time(datetime.now() + timedelta(days=20))

trigger = WorkloadMgrTrigger(u'{"startdate":"06/15/2014","enddate":"No End","starttime":"12:00am","interval":"1 hr","snapshotstokeep":"10"}')
print trigger.get_next_fire_time(datetime.now())
print trigger.get_next_fire_time(datetime.now() + timedelta(days=20))
"""
