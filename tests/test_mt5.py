from __future__ import annotations

from collections import namedtuple

from trader.mt5 import MetaTrader5Client, classify_asset_class


def test_classify_asset_class_uses_symbol_metadata() -> None:
    assert classify_asset_class(path="Forex\\Majors\\EURUSD", name="EURUSD") == "forex"
    assert classify_asset_class(path="Crypto\\BTCUSD", description="Bitcoin vs US Dollar") == "crypto"
    assert classify_asset_class(path="Stocks\\US\\AAPL") == "stocks"


def test_build_market_order_request_uses_tick_side_price() -> None:
    SymbolInfo = namedtuple("SymbolInfo", ["filling_mode"])
    Tick = namedtuple("Tick", ["ask", "bid"])

    class FakeMt5Module:
        TRADE_ACTION_DEAL = 1
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1
        ORDER_TIME_GTC = 0
        ORDER_FILLING_RETURN = 2

        def symbol_select(self, symbol, enabled):
            return True

        def symbol_info(self, symbol):
            return SymbolInfo(filling_mode=self.ORDER_FILLING_RETURN)

        def symbol_info_tick(self, symbol):
            return Tick(ask=1.1010, bid=1.1008)

    client = MetaTrader5Client(module=FakeMt5Module())
    client._connected = True

    request = client.build_market_order_request(
        symbol="EURUSD",
        side="buy",
        volume=0.1,
        stop_loss=1.0950,
        take_profit=1.1100,
    )

    assert request["symbol"] == "EURUSD"
    assert request["type"] == FakeMt5Module.ORDER_TYPE_BUY
    assert request["price"] == 1.1010
    assert request["sl"] == 1.0950
    assert request["tp"] == 1.1100


def test_build_close_position_request_uses_opposite_side_price() -> None:
    SymbolInfo = namedtuple("SymbolInfo", ["filling_mode"])
    Tick = namedtuple("Tick", ["ask", "bid"])

    class FakeMt5Module:
        TRADE_ACTION_DEAL = 1
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1
        ORDER_TIME_GTC = 0
        ORDER_FILLING_RETURN = 2

        def symbol_select(self, symbol, enabled):
            return True

        def symbol_info(self, symbol):
            return SymbolInfo(filling_mode=self.ORDER_FILLING_RETURN)

        def symbol_info_tick(self, symbol):
            return Tick(ask=1.1010, bid=1.1008)

    client = MetaTrader5Client(module=FakeMt5Module())
    client._connected = True

    request = client.build_close_position_request(
        symbol="EURUSD",
        side="buy",
        volume=0.1,
        position_ticket=123456,
    )

    assert request["symbol"] == "EURUSD"
    assert request["type"] == FakeMt5Module.ORDER_TYPE_SELL
    assert request["price"] == 1.1008
    assert request["position"] == 123456
