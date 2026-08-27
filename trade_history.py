import MetaTrader5 as mt5
from datetime import datetime
import mt5_connect

mt5_connect.initialize_mt5()

from_date = datetime(2026, 1, 1)
to_date = datetime.now()

deals = mt5.history_deals_get(from_date, to_date)

if deals is None:
    print("History query failed:", mt5.last_error())
    mt5.shutdown()
    raise SystemExit


for index, deal in enumerate(deals):
    print("\nDeal Ticket", index)
    print("Deal Ticket: ", deal.ticket)
    print("Position ID: ", deal.position_id)
    print("Symbol: ", deal.symbol)
    print("Volume: ", deal.volume)
    print("Price: ", deal.price)
    print("Profit: ", deal.profit)
    

mt5.shutdown()

