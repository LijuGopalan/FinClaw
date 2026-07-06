import sys
import pandas as pd
from arkfunds import ETF

def test_ark():
    try:
        arkk = ETF('ARKK')
        df = arkk.trades()
        print("ARK TRADES:")
        print(df.head())
    except Exception as e:
        print(f"ARK Error: {e}")

if __name__ == "__main__":
    test_ark()
