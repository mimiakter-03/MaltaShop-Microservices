import json, logging, os, sqlite3, time
import pika

logging.basicConfig(level=logging.INFO, format='%(message)s')
DB = os.getenv('NOTIFICATION_DB','/data/notifications.db')
BROKER = os.getenv('RABBITMQ_HOST','rabbitmq')

def database():
    os.makedirs(os.path.dirname(DB) or '.',exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute('CREATE TABLE IF NOT EXISTS notifications (order_id TEXT PRIMARY KEY, correlation_id TEXT NOT NULL, message TEXT NOT NULL)')
    con.commit()
    return con

def handle_event(body):
    event = json.loads(body)
    if event.get('event') != 'OrderPlaced' or not event.get('order_id') or not event.get('correlation_id'):
        raise ValueError('invalid event')
    con = database()
    try:
        con.execute('INSERT OR IGNORE INTO notifications VALUES (?,?,?)', (event['order_id'],event['correlation_id'],f"Order {event['order_id']} received"))
        con.commit()
    finally:
        con.close()
    logging.info(json.dumps({'service':'notification','action':'event_consumed','order_id':event['order_id'],'correlation_id':event['correlation_id']}))

def main():
    database()
    while True:
        try:
            conn = pika.BlockingConnection(pika.ConnectionParameters(host=BROKER, heartbeat=30))
            ch = conn.channel()
            ch.queue_declare(queue='order_placed',durable=True)
            ch.basic_qos(prefetch_count=1)
            def callback(channel, method, properties, body):
                try:
                    handle_event(body)
                    channel.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as exc:
                    logging.error(json.dumps({'service':'notification','action':'consume_failed','error':str(exc)}))
                    # Demo policy: malformed messages are discarded; production should use a dead-letter queue.
                    channel.basic_nack(delivery_tag=method.delivery_tag,requeue=False)
            ch.basic_consume(queue='order_placed',on_message_callback=callback)
            ch.start_consuming()
        except (pika.exceptions.AMQPError,OSError) as exc:
            logging.warning(json.dumps({'service':'notification','action':'reconnect','error':str(exc)}))
            time.sleep(5)

if __name__ == '__main__': main()
