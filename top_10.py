python -c "
import sqlite3
conn = sqlite3.connect('data/lotto.db')
numbers = {}
for row in conn.execute('SELECT numbers FROM draws'):
    for n in row[0].split(','):
        numbers[n] = numbers.get(n, 0) + 1
top_10 = sorted(numbers.items(), key=lambda x: x[1], reverse=True)[:10]
print('Top 10 most frequent numbers:')
for n, count in top_10:
    print(f'  {n}: {count} times')
conn.close()
"