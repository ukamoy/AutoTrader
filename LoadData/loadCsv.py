"""
导入CSV历史数据到MongoDB中
"""
import pandas as pd
from datetime import datetime, timedelta
from time import time
import pymongo
from vnpy.trader.app.ctaStrategy.ctaBase import SETTING_DB_NAME, TICK_DB_NAME, MINUTE_DB_NAME, DAILY_DB_NAME
from vnpy.trader.vtGlobal import globalSetting
from vnpy.trader.vtConstant import *
from vnpy.trader.vtObject import VtBarData

"""settigs"""
mongoURI = "mongodb://localhost:27017"
db_name = MINUTE_DB_NAME
csv_file = 'bch_usdt.csv'
symbol_name = 'bch_usdt:OKEX'

def loadCoinCsv(fileName, dbName, symbol):
    """将OKEX导出的csv格式的历史分钟数据插入到Mongo数据库中"""
    start = time()
    print('开始读取CSV文件%s中的数据插入到%s的%s中' %(fileName, dbName, symbol))

    # 锁定集合，并创建索引
    client = pymongo.MongoClient(mongoURI)
    collection = client[dbName][symbol]
    collection.ensure_index([('datetime', pymongo.ASCENDING)], unique=True)

    # 读取数据和插入到数据库
    data_df = pd.read_csv(fileName)
    for index, row in data_df.iterrows():
        bar = VtBarData()
        bar.open = float(row.open)
        bar.close = float(row.close)
        bar.high = float(row.high)
        bar.low = float(row.low)
        bar.volume = row.volume
        bar.vtSymbol = symbol
        bar.symbol, bar.exchange = symbol.split(':')
        bar.datetime = row.datetime
        bar.date = bar.datetime.date().strftime('%Y%m%d')
        bar.time = bar.datetime.time().strftime('%H:%M:%S')
        flt = {'datetime': bar.datetime}
        collection.update_one(flt, {'$set':bar.__dict__}, upsert=True)
        print('%s \t %s' % (bar.date, bar.time))
    print('插入完毕，耗时：%s' % (time()-start))

if __name__ == '__main__':
    loadCoinCsv(csv_file, db_name, symbol_name)