# encoding: UTF-8
"""展示如何执行策略参数优化"""
from vnpy.trader.app.ctaStrategy import BacktestingEngine
from vnpy.trader.app.ctaStrategy.ctaBacktesting import OptimizationSetting
from datetime import datetime
import pandas as pd
import os
import sys
import json

SETTING_FILE = 'opt_settings.json'

def start_optimize_n_output(engine, task, param_mode, opt_engine_setting, folderName, strategy, opt_target):
    for param in task[param_mode]:
        opt_engine_setting.addParameter(param["param_name"], *param["range"])
    opt_output = engine.runParallelOptimization(strategy, opt_engine_setting)
    result_list = []
    col=[]
    for result in opt_output:
        param,target,stat = result
        param = eval(param)
        result_dict = {**param, **stat}
        result_list.append(result_dict)
    col.extend(param.keys())
    col.extend(['sharpeRatio','endBalance','totalReturn','maxDdPercent','totalDays','totalTradeCount'])
    result_df = pd.DataFrame(result_list, columns=col)
    result_df.sort_values(opt_target, ascending = False, inplace = True)
    result_df.to_csv(f"{folderName}/opt_{task['task_name']}.csv")
    func = STR_FUNC_PAIR[param_mode]
    for param in task[param_mode]:
        pick = func(result_df, param["param_name"])
        opt_engine_setting.paramDict[param["param_name"]] = pick
    return opt_engine_setting.paramDict

def pick_opt_param(df, param_name):
    count = 0
    for i in [20,10,5]:
        opt=df.head(i)
        count += opt[param_name].value_counts()
    return [float(count.idxmax())]

def pick_best_param(df, param_name):
    best_param = list(df[param_name])[0]
    return [best_param]

STR_FUNC_PAIR = {"pick_opt_param": pick_opt_param,
                'pick_best_param': pick_best_param}

def startBacktestingEngine(engine_settings):
    # 创建回测引擎，模式为K线
    engine = BacktestingEngine()
    for attr, engine_setting in engine_settings.items():
        func = engine.__getattribute__(attr)
        func(engine_setting)
    return engine

def createFolder(STRATEGY_SETTING):
    strategy = STRATEGY_SETTING["strategy_filename"].replace("Strategy","") 
    symbol = STRATEGY_SETTING["symbolList"][0].replace(":",".")
    now = datetime.now().strftime("%m%d%H%M")
    folder_name = '_'.join([strategy,symbol,now]) 
    os.makedirs(folder_name)
    return folder_name

def loadStrategy(STRATEGY_SETTING, pardir = None):
    from importlib import import_module
    if pardir:
        STRATEGY_SETTING['strategy_filename'] = pardir + '.' + STRATEGY_SETTING['strategy_filename']
    module = import_module(STRATEGY_SETTING["strategy_filename"])
    return getattr(module, STRATEGY_SETTING["strategy_modulename"])

def loadSettings():
    with open(SETTING_FILE) as f:
        setting = json.load(f,)
    return setting

def run_tasks(pardir = None):
    if pardir:
        os.chdir(pardir)
        sys.path.append(pardir)
    setting = loadSettings()
    STRATEGY_SETTING = setting['STRATEGY_SETTING']
    
    folderName = createFolder(STRATEGY_SETTING)
    opt_engine_setting = OptimizationSetting()
    opt_engine_setting.setOptimizeTarget(setting["OPT_TARGET"])
    opt_engine_setting.addParameter("symbolList", STRATEGY_SETTING["symbolList"])
    engine = startBacktestingEngine(setting['ENGINE_SETTINGS'])
    strategy = loadStrategy(STRATEGY_SETTING, pardir)
    for task in setting['TASK_LISTS']:
        task_name, param_mode = task
        opt_result = start_optimize_n_output(
            engine, task, param_mode, opt_engine_setting, folderName, strategy, setting["OPT_TARGET"])
    with open(f'{folderName}/opt_result_summary.json', "w", encoding="utf-8") as f:
        json.dump(opt_result, f, indent=4)
    print("*** tasks finished ****")

if __name__ == '__main__':
    run_tasks()