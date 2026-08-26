import MetaTrader5 as mt5

if not mt5.initialize():
    print("MT5 connection failed:", mt5.last_error())
    raise SystemExit

account = mt5.account_info()

print("Connected account:", account.login)
print("Balance:", account.balance)
print("Equity:", account.equity)