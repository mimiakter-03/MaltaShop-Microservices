import json, os, sqlite3, uuid, time, logging
from flask import Flask, request, jsonify
import pika

app = Flask(__name__)
DB = os.getenv('ORDER_DB', '/data/orders.db')
BROKER = os.getenv('RABBITMQ_HOST', 'rabbitmq')
logging.basicConfig(level=logging.INFO, format='%(message)s')

def database():
    os.makedirs(os.path.dirname(DB) or '.', exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute('CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, product TEXT NOT NULL, quantity INTEGER NOT NULL, status TEXT NOT NULL, correlation_id TEXT NOT NULL, published INTEGER DEFAULT 0)')
    con.commit()
    return con

def publish_pending():
    con = database()
    pending = con.execute('SELECT id, product, quantity, correlation_id FROM orders WHERE published=0').fetchall()
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=BROKER, heartbeat=30, blocked_connection_timeout=10))
        channel = connection.channel()
        channel.queue_declare(queue='order_placed', durable=True)
        channel.confirm_delivery()
        for oid, product, quantity, correlation_id in pending:
            event = {'event': 'OrderPlaced', 'order_id': oid, 'product': product, 'quantity': quantity, 'correlation_id': correlation_id}
            channel.basic_publish(exchange='', routing_key='order_placed', body=json.dumps(event), properties=pika.BasicProperties(delivery_mode=2, correlation_id=correlation_id), mandatory=True)
            con.execute('UPDATE orders SET published=1 WHERE id=?', (oid,))
            con.commit()
            logging.info(json.dumps({'service':'order','action':'event_published','order_id':oid,'correlation_id':correlation_id}))
        connection.close()
        return True
    except (pika.exceptions.AMQPError, OSError) as exc:
        logging.warning(json.dumps({'service':'order','action':'broker_unavailable','error':str(exc)}))
        return False
    finally:
        con.close()

@app.get('/health')
def health():
    try:
        con = database(); con.execute('SELECT 1'); con.close()
        return jsonify(status='ok'), 200
    except sqlite3.Error:
        return jsonify(status='unhealthy'), 503

@app.post('/orders')
def place_order():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('product'), str) or not data['product'].strip() or type(data.get('quantity')) is not int or not (1 <= data['quantity'] <= 100):
        return jsonify(error='product must be a non-empty string and quantity must be 1-100'), 400
    oid = str(uuid.uuid4())
    correlation_id = request.headers.get('X-Correlation-ID') or str(uuid.uuid4())
    con = database()
    con.execute('INSERT INTO orders (id,product,quantity,status,correlation_id) VALUES (?,?,?,?,?)', (oid,data['product'].strip(),data['quantity'],'RECEIVED',correlation_id))
    con.commit(); con.close()
    logging.info(json.dumps({'service':'order','action':'order_created','order_id':oid,'correlation_id':correlation_id}))
    published = publish_pending()
    return jsonify(order_id=oid,status='RECEIVED',event_published=published,correlation_id=correlation_id), 202

@app.get('/orders/<order_id>')
def get_order(order_id):
    con = database(); row = con.execute('SELECT id,product,quantity,status,correlation_id,published FROM orders WHERE id=?',(order_id,)).fetchone(); con.close()
    if not row: return jsonify(error='not found'),404
    return jsonify(order_id=row[0],product=row[1],quantity=row[2],status=row[3],correlation_id=row[4],event_published=bool(row[5]))

@app.post('/admin/retry-events')
def retry_events():
    # Demo-only endpoint; protect with authentication or replace with background worker before production.
    if request.headers.get('X-Demo-Admin-Key') != os.getenv('DEMO_ADMIN_KEY','change-me'):
        return jsonify(error='forbidden'),403
    return jsonify(published=publish_pending())

if __name__ == '__main__':
    database()
    app.run(host='0.0.0.0',port=5000)
