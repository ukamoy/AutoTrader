# encoding: UTF-8

from vnpy.trader import vtConstant
from .ctptestGateway import CtpGateway

gatewayClass = CtpGateway
gatewayName = 'CTPTEST'
gatewayDisplayName = 'CTPTEST'
gatewayType = vtConstant.GATEWAYTYPE_FUTURES
gatewayQryEnabled = True
