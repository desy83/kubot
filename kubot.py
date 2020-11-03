import sched, time
import socket
import requests

from kucoin.client import Margin, User
from config.config import config
from logger import Logger
from datetime import datetime, date, timedelta
from pushover import Client


class Scheduler(object):
    def __init__(self):
        self.__client = Margin(config.api_key, config.api_secret, config.api_passphrase)
        self.__user = User(config.api_key, config.api_secret, config.api_passphrase)
        self.__pushover = Client(config.user_key, api_token=config.api_token)
        self.__scheduler = sched.scheduler(time.time, time.sleep)
        self.schedule_checks(config.interval)
        self.__scheduler.run()

    def schedule_checks(self, interval):
        self.__scheduler.enter(interval, 1, self.schedule_checks, argument=(interval,))
        try:
            min_int_rate = self.get_min_daily_interest_rate()
            self.check_active_loans(min_int_rate)
            self.lend_loans(min_int_rate)
            self.check_active_lendings()
        except (socket.timeout, requests.exceptions.Timeout) as e:
            Logger().logger.error("Transport Exception occured: %s", e)

    def lend_loans(self, min_int_rate):
        account_list = self.__user.get_account_list('USDT', 'main')
        account = next((x for x in account_list if x['currency'] == 'USDT'), None)
        if account:
            available = int(float(account['available']))
            if available:
                if min_int_rate >= config.minimum_rate:
                    rate = float(format(min_int_rate + config.charge, '.5f'))
                else:
                    rate = config.minimum_rate
                order_id = self.__client.create_lend_order('USDT', str(available), str(rate), 28)
                info = "Create Lend Order: %s, Amount: %s, Rate: %s" % (order_id, available, rate)
                Logger().logger.info(info)
                self.__pushover.send_message(info, title="Create Lend Order")
            else:
                Logger().logger.info("Insufficient Amount on Main Account: %s", available)

    def check_active_loans(self, min_int_rate):
        active_orders = self.__client.get_active_order(currency="USDT")
        for a in active_orders.get('items'):
            daily_int_rate = float(a['dailyIntRate'])
            if abs(daily_int_rate - min_int_rate) >= config.correction and not (daily_int_rate == config.minimum_rate and min_int_rate - config.correction <= config.minimum_rate):
                self.__client.cancel_lend_order(a['orderId'])
                Logger().logger.info("Cancel Lend Order: Amount: %s, DailyIntRate: %s, "
                                     "MinIntRate: %s, DiffRate: %s, Correction: %s",
                                     a['size'],
                                     daily_int_rate,
                                     min_int_rate,
                                     abs(daily_int_rate - min_int_rate),
                                     config.correction
                                     )

    def get_min_daily_interest_rate(self):
        lending_market = self.__client.get_lending_market("USDT")
        if lending_market:
            return float(lending_market[0]['dailyIntRate'])
        else:
            return config.default_interest

    def check_active_lendings(self):
        active_list = self.__client.get_active_list(pageSize=50)
        if active_list and active_list['items']:
            utc_now = datetime.utcnow().time()
            dt = timedelta(seconds=config.interval).total_seconds()
            for a in active_list['items']:
                maturity_timestamp = a['maturityTime'] / 1000
                time_diff = abs((datetime.combine(date.min, utc_now) - datetime.combine(date.min, datetime.utcfromtimestamp(maturity_timestamp).time())).total_seconds())
                print(dt, time_diff, time_diff <= dt)
                if time_diff <= dt:
                    maturity_date = datetime.fromtimestamp(maturity_timestamp).strftime("%Y-%m-%d %H:%M:%S")
                    self.__pushover.send_message("Create Active Lending: Amount: {}, DailyIntRate: {}, MaturityDate: {}, AccruedInterest: {}".format(
                        a['size'],
                        a['dailyIntRate'],
                        maturity_date,
                        a['accruedInterest'])
                    , title="Create Active Lending")


def main():
    Scheduler()


if __name__ == "__main__":
    main()
