"""MetaTrader 5 helpers for account inspection, symbols, quotes, and order checks."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Any

import pandas as pd

from trader.config import MT5_TIMEFRAME_ATTR_MAP, normalize_symbol, validate_timeframe


class Mt5Error(RuntimeError):
    """Base MetaTrader 5 integration error."""


class Mt5UnavailableError(Mt5Error):
    """Raised when the MetaTrader5 Python package is not available."""


@dataclass(frozen=True)
class Mt5ConnectionSettings:
    path: str | None = None
    login: int | None = None
    password: str | None = None
    server: str | None = None
    timeout: int | None = None
    portable: bool | None = None

    @classmethod
    def from_env(cls) -> "Mt5ConnectionSettings":
        login = os.getenv("MT5_LOGIN")
        timeout = os.getenv("MT5_TIMEOUT")
        portable = os.getenv("MT5_PORTABLE")

        return cls(
            path=os.getenv("MT5_PATH"),
            login=int(login) if login else None,
            password=os.getenv("MT5_PASSWORD"),
            server=os.getenv("MT5_SERVER"),
            timeout=int(timeout) if timeout else None,
            portable=_parse_bool(portable) if portable is not None else None,
        )


class MetaTrader5Client:
    def __init__(
        self,
        settings: Mt5ConnectionSettings | None = None,
        module: Any | None = None,
    ) -> None:
        self.settings = settings or Mt5ConnectionSettings.from_env()
        self._module = module if module is not None else self._import_module()
        self._connected = False

    @staticmethod
    def _import_module():
        try:
            return importlib.import_module("MetaTrader5")
        except ImportError:
            return None

    @classmethod
    def from_env(cls) -> "MetaTrader5Client":
        return cls(settings=Mt5ConnectionSettings.from_env())

    def is_available(self) -> bool:
        return self._module is not None

    def connect(self) -> "MetaTrader5Client":
        mt5 = self._require_module()

        init_kwargs = {}
        if self.settings.path:
            init_kwargs["path"] = self.settings.path
        if self.settings.timeout is not None:
            init_kwargs["timeout"] = self.settings.timeout
        if self.settings.portable is not None:
            init_kwargs["portable"] = self.settings.portable

        if not mt5.initialize(**init_kwargs):
            raise Mt5Error(f"MT5 initialize() fehlgeschlagen: {mt5.last_error()}")

        self._connected = True

        if self.settings.login is not None:
            login_kwargs = {"login": self.settings.login}
            if self.settings.password:
                login_kwargs["password"] = self.settings.password
            if self.settings.server:
                login_kwargs["server"] = self.settings.server

            if not mt5.login(**login_kwargs):
                self.shutdown()
                raise Mt5Error(f"MT5 login() fehlgeschlagen: {mt5.last_error()}")

        return self

    def shutdown(self) -> None:
        if self._module and self._connected:
            self._module.shutdown()
            self._connected = False

    def __enter__(self) -> "MetaTrader5Client":
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()

    def account_info(self) -> dict[str, Any]:
        self._require_connected()
        info = self._module.account_info()
        if info is None:
            raise Mt5Error(f"MT5 account_info() fehlgeschlagen: {self._module.last_error()}")
        return _namedtuple_to_dict(info)

    def terminal_info(self) -> dict[str, Any]:
        self._require_connected()
        info = self._module.terminal_info()
        if info is None:
            raise Mt5Error(f"MT5 terminal_info() fehlgeschlagen: {self._module.last_error()}")
        return _namedtuple_to_dict(info)

    def symbols(self, group: str | None = None) -> pd.DataFrame:
        self._require_connected()
        records = self._module.symbols_get(group=group) if group else self._module.symbols_get()
        if records is None:
            raise Mt5Error(f"MT5 symbols_get() fehlgeschlagen: {self._module.last_error()}")

        rows = [_namedtuple_to_dict(record) for record in records]
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame

        for column in ("path", "description", "category", "exchange", "name"):
            if column not in frame.columns:
                frame[column] = ""

        frame["asset_class"] = frame.apply(
            lambda row: classify_asset_class(
                path=row.get("path"),
                description=row.get("description"),
                category=row.get("category"),
                exchange=row.get("exchange"),
                name=row.get("name"),
            ),
            axis=1,
        )
        return frame.sort_values(["asset_class", "path", "name"]).reset_index(drop=True)

    def asset_summary(self, group: str | None = None) -> pd.DataFrame:
        symbols = self.symbols(group=group)
        if symbols.empty:
            return pd.DataFrame(columns=["asset_class", "count"])
        summary = symbols.groupby("asset_class", as_index=False).size()
        return summary.rename(columns={"size": "count"}).sort_values("count", ascending=False)

    def symbol_info(self, symbol: str) -> dict[str, Any]:
        self._require_connected()
        selected_symbol = self._ensure_symbol(symbol)
        info = self._module.symbol_info(selected_symbol)
        if info is None:
            raise Mt5Error(
                f"MT5 symbol_info() lieferte keine Daten fuer {selected_symbol}: {self._module.last_error()}"
            )
        payload = _namedtuple_to_dict(info)
        payload["asset_class"] = classify_asset_class(
            path=payload.get("path"),
            description=payload.get("description"),
            category=payload.get("category"),
            exchange=payload.get("exchange"),
            name=payload.get("name"),
        )
        return payload

    def quote(self, symbol: str) -> dict[str, Any]:
        self._require_connected()
        selected_symbol = self._ensure_symbol(symbol)
        tick = self._module.symbol_info_tick(selected_symbol)
        if tick is None:
            raise Mt5Error(
                f"MT5 symbol_info_tick() lieferte keine Daten fuer {selected_symbol}: {self._module.last_error()}"
            )
        payload = _namedtuple_to_dict(tick)
        payload["symbol"] = selected_symbol
        return payload

    def open_positions(self, symbol: str | None = None, group: str | None = None) -> pd.DataFrame:
        self._require_connected()
        if symbol:
            records = self._module.positions_get(symbol=symbol)
        elif group:
            records = self._module.positions_get(group=group)
        else:
            records = self._module.positions_get()
        return _tuple_records_to_frame(records)

    def active_orders(self, symbol: str | None = None, group: str | None = None) -> pd.DataFrame:
        self._require_connected()
        if symbol:
            records = self._module.orders_get(symbol=symbol)
        elif group:
            records = self._module.orders_get(group=group)
        else:
            records = self._module.orders_get()
        return _tuple_records_to_frame(records)

    def copy_rates(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        self._require_connected()

        selected_symbol = self._ensure_symbol(symbol)
        validated_timeframe = validate_timeframe(timeframe)
        timeframe_attr = MT5_TIMEFRAME_ATTR_MAP[validated_timeframe]
        rates = self._module.copy_rates_from_pos(
            selected_symbol,
            getattr(self._module, timeframe_attr),
            0,
            bars,
        )
        if rates is None:
            raise Mt5Error(
                f"MT5 copy_rates_from_pos() lieferte keine Daten fuer {selected_symbol}: {self._module.last_error()}"
            )

        frame = pd.DataFrame(rates)
        if frame.empty:
            raise Mt5Error(f"MT5 lieferte ein leeres DataFrame fuer {selected_symbol}.")

        frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        frame = frame.rename(columns={"tick_volume": "volume"})
        frame["tick_volume"] = frame["volume"]
        frame["symbol"] = selected_symbol
        frame["timeframe"] = validated_timeframe
        frame["data_source"] = "metatrader5"

        expected_columns = [
            "time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "tick_volume",
            "spread",
            "real_volume",
            "symbol",
            "timeframe",
            "data_source",
        ]
        return frame[expected_columns].sort_values("time").reset_index(drop=True)

    def estimate_margin(self, symbol: str, side: str, volume: float, price: float) -> float:
        self._require_connected()
        action = self._order_type(side)
        margin = self._module.order_calc_margin(action, symbol, volume, price)
        if margin is None:
            raise Mt5Error(f"MT5 order_calc_margin() fehlgeschlagen: {self._module.last_error()}")
        return float(margin)

    def estimate_profit(
        self,
        symbol: str,
        side: str,
        volume: float,
        price_open: float,
        price_close: float,
    ) -> float:
        self._require_connected()
        action = self._order_type(side)
        profit = self._module.order_calc_profit(action, symbol, volume, price_open, price_close)
        if profit is None:
            raise Mt5Error(f"MT5 order_calc_profit() fehlgeschlagen: {self._module.last_error()}")
        return float(profit)

    def check_market_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        deviation: int = 20,
        comment: str = "trader-order-check",
        magic: int = 234000,
    ) -> dict[str, Any]:
        request = self.build_market_order_request(
            symbol=symbol,
            side=side,
            volume=volume,
            stop_loss=stop_loss,
            take_profit=take_profit,
            deviation=deviation,
            comment=comment,
            magic=magic,
        )
        result = self._module.order_check(request)
        if result is None:
            raise Mt5Error(f"MT5 order_check() fehlgeschlagen: {self._module.last_error()}")
        payload = _namedtuple_to_dict(result)
        payload["request"] = request
        return payload

    def send_market_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        deviation: int = 20,
        comment: str = "trader-live-order",
        magic: int = 234000,
    ) -> dict[str, Any]:
        request = self.build_market_order_request(
            symbol=symbol,
            side=side,
            volume=volume,
            stop_loss=stop_loss,
            take_profit=take_profit,
            deviation=deviation,
            comment=comment,
            magic=magic,
        )
        result = self._module.order_send(request)
        if result is None:
            raise Mt5Error(f"MT5 order_send() fehlgeschlagen: {self._module.last_error()}")
        payload = _namedtuple_to_dict(result)
        payload["request"] = request
        return payload

    def build_market_order_request(
        self,
        symbol: str,
        side: str,
        volume: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        deviation: int = 20,
        comment: str = "trader-order",
        magic: int = 234000,
    ) -> dict[str, Any]:
        self._require_connected()
        selected_symbol = self._ensure_symbol(symbol)
        symbol_info = self._module.symbol_info(selected_symbol)
        tick = self._module.symbol_info_tick(selected_symbol)

        if symbol_info is None or tick is None:
            raise Mt5Error(
                f"MT5 konnte keine Symboldaten fuer {selected_symbol} laden: {self._module.last_error()}"
            )

        order_type = self._order_type(side)
        price = float(tick.ask if side.lower() == "buy" else tick.bid)

        request = {
            "action": self._module.TRADE_ACTION_DEAL,
            "symbol": selected_symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": comment,
            "type_time": self._module.ORDER_TIME_GTC,
            "type_filling": _preferred_fill_type(self._module, symbol_info),
        }

        if stop_loss is not None:
            request["sl"] = float(stop_loss)
        if take_profit is not None:
            request["tp"] = float(take_profit)
        return request

    def _ensure_symbol(self, symbol: str) -> str:
        self._require_connected()

        normalized = normalize_symbol(symbol) if _looks_like_forex(symbol) else symbol.strip().upper()
        if not self._module.symbol_select(normalized, True):
            raise Mt5Error(f"MT5 konnte das Symbol {normalized} nicht aktivieren: {self._module.last_error()}")
        return normalized

    def _order_type(self, side: str):
        direction = side.lower()
        if direction == "buy":
            return self._module.ORDER_TYPE_BUY
        if direction == "sell":
            return self._module.ORDER_TYPE_SELL
        raise ValueError("side muss 'buy' oder 'sell' sein.")

    def _require_module(self):
        if self._module is None:
            raise Mt5UnavailableError(
                "MetaTrader5 ist in dieser Python-Umgebung nicht installiert oder nicht verfuegbar."
            )
        return self._module

    def _require_connected(self) -> None:
        self._require_module()
        if not self._connected:
            raise Mt5Error("MetaTrader5Client ist nicht verbunden. Verwende connect() oder den Context Manager.")


def classify_asset_class(
    path: str | None = None,
    description: str | None = None,
    category: str | None = None,
    exchange: str | None = None,
    name: str | None = None,
) -> str:
    joined = " ".join(
        str(value or "").lower()
        for value in (path, description, category, exchange, name)
    )

    if _looks_like_forex(name or "") or "forex" in joined or "fx" in joined:
        return "forex"
    if any(token in joined for token in ("crypto", "bitcoin", "ethereum", "btc", "eth", "xrp", "sol")):
        return "crypto"
    if any(token in joined for token in ("metal", "gold", "silver", "xau", "xag", "xpt", "xpd")):
        return "metals"
    if any(token in joined for token in ("energy", "oil", "brent", "wti", "gas", "natural gas")):
        return "energy"
    if any(token in joined for token in ("future", "futures", "micro e-mini", "contract")):
        return "futures"
    if any(token in joined for token in ("index", "indices", "nas100", "us30", "spx", "dax", "nikkei")):
        return "indices"
    if any(token in joined for token in ("etf",)):
        return "etf"
    if any(token in joined for token in ("bond", "treasury", "bund", "note")):
        return "bonds"
    if any(token in joined for token in ("option", "call", "put")):
        return "options"
    if any(token in joined for token in ("stock", "stocks", "share", "shares", "equity", "equities")):
        return "stocks"
    if any(token in joined for token in ("commodity", "commodities", "cocoa", "coffee", "corn", "soy", "wheat", "sugar", "cotton")):
        return "commodities"
    return "unknown"


def _tuple_records_to_frame(records: Any) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    return pd.DataFrame([_namedtuple_to_dict(record) for record in records])


def _namedtuple_to_dict(value: Any) -> dict[str, Any]:
    return value._asdict() if hasattr(value, "_asdict") else dict(value)


def _preferred_fill_type(mt5_module, symbol_info) -> int:
    filling_mode = getattr(symbol_info, "filling_mode", None)
    candidates = [
        getattr(mt5_module, "ORDER_FILLING_RETURN", None),
        getattr(mt5_module, "ORDER_FILLING_IOC", None),
        getattr(mt5_module, "ORDER_FILLING_FOK", None),
    ]
    available = [candidate for candidate in candidates if candidate is not None]

    if filling_mode in available:
        return int(filling_mode)
    if available:
        return int(available[0])
    raise Mt5Error("Es konnte kein gueltiger type_filling fuer MT5 bestimmt werden.")


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Ungueltiger Boolean-Wert fuer MT5_PORTABLE: {value}")


def _looks_like_forex(symbol: str) -> bool:
    cleaned = symbol.replace("/", "").replace(" ", "").upper()
    return len(cleaned) == 6 and cleaned.isalpha()
