"""
导入CSV历史数据到PICKLE缓存文件中
"""
import pandas as pd
from datetime import datetime
import _pickle
import os
"""settigs"""
symbol_name = "rb:SHF"
csv_file = "2019.csv"
cache_path = "D:/vnpy_data/"

def save_pkl(symbol, csv_file):
    save_path = os.path.join(cache_path, "bar",)
    if not os.path.isdir(save_path):
        os.makedirs(save_path)
    pkl_file_path = f'{save_path}/{symbol.replace(":", "_")}.pkl'
    if os.path.isfile(pkl_file_path):
        # 读取 pkl
        pkl_file = open(pkl_file_path, 'rb')
        df_cached = _pickle.load(pkl_file)
        pkl_file.close()
    else:
        df_cached = pd.DataFrame([])

    data_df = pd.read_csv(csv_file) 
    data_df['datetime'] = data_df['datetime'].apply(lambda x : datetime.strptime(x,"%Y%m%d %H:%M:%S"))
    data_df['date'] = data_df['datetime'].apply(lambda x : x.strftime("%Y%m%d"))
    data_df['time'] = data_df['datetime'].apply(lambda x : x.strftime("%H:%M:%S"))
    data_df[['open','high','low','close']]= data_df[['open','high','low','close']].applymap(lambda x: float(x))
    data_df['volume'] =data_df['volume'].apply(lambda x: int(x))
    data_df['vtSymbol'] = symbol
    data_df['symbol'] = symbol
    data_df['exchange'] = None
    data_df['openInterest']=data_df['open_interest']

    row, column= df_cached.shape
    row_csv,column = data_df.shape
    print(f"读取总条数:{row}")
    print(f"csv总行数：{row_csv}")

    df_cached = df_cached.append(data_df)
    df_cached.drop_duplicates(subset =['datetime'], inplace = True)
    row1,column = df_cached.shape
    diff = int(row1 - row)

    print(f"插入{diff}条, 存入{row1}条")
    output = open(pkl_file_path, 'wb')
    df_cached.sort_values(by='datetime', ascending=True, inplace=True)
    _pickle.dump(df_cached, output)
    output.close()

if __name__ == '__main__':
    save_pkl(symbol_name, csv_file)