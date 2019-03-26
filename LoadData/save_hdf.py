import pandas as pd
from datetime import datetime
import os

symbol = "rb:SHF"
csv_file = "2019.csv"
cache_folder = "D:/vnpy_data/"

def save_hdf(symbol,csv_file,sheetname = ""):
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

    date = set(data_df['date'])
    print(date)

    if data_df.size > 0:
        save_path = os.path.join(cache_folder, "bar", symbol.replace(":", "_"))
        if not os.path.isdir(save_path):
            os.makedirs(save_path)
        for single_date in date:
            file_data = data_df[data_df["date"] == single_date]
            if file_data.size > 0:
                hdf_file_path = f'{save_path}/{single_date}.hd5'
                if os.path.isfile(hdf_file_path):
                    cache_df = pd.read_hdf(hdf_file_path)
                    file_data = file_data.append(cache_df)
                    file_data.drop_duplicates(subset = "datetime", inplace=True)
                file_data.to_hdf(hdf_file_path, "/", append=True)

if __name__ == '__main__':
    save_hdf(symbol, csv_file)