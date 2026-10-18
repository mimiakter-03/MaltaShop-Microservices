import importlib.util, json, os, tempfile, unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(__file__))
def load(name, path):
    spec = importlib.util.spec_from_file_location(name,os.path.join(ROOT,path))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
order = load('order','order-service/app.py')
notification = load('notification','notification-service/worker.py')

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        order.DB = os.path.join(self.temp.name,'orders.db')
        notification.DB = os.path.join(self.temp.name,'notifications.db')
        self.client = order.app.test_client()
    def tearDown(self): self.temp.cleanup()
    def test_validation(self):
        self.assertEqual(self.client.post('/orders',json={'product':'Phone','quantity':0}).status_code,400)
        self.assertEqual(self.client.post('/orders',json={'product':'Phone','quantity':True}).status_code,400)
    def test_health(self):
        self.assertEqual(self.client.get('/health').status_code,200)
    def test_create_and_contract(self):
        with patch.object(order,'publish_pending',return_value=False):
            response=self.client.post('/orders',json={'product':'Phone','quantity':2},headers={'X-Correlation-ID':'test-123'})
        self.assertEqual(response.status_code,202)
        body=response.get_json()
        self.assertEqual(body['correlation_id'],'test-123')
        event={'event':'OrderPlaced','order_id':body['order_id'],'product':'Phone','quantity':2,'correlation_id':body['correlation_id']}
        notification.handle_event(json.dumps(event).encode())
        notification.handle_event(json.dumps(event).encode())
        con=notification.database(); count=con.execute('SELECT COUNT(*) FROM notifications').fetchone()[0];con.close()
        self.assertEqual(count,1)
        self.assertEqual(self.client.get('/orders/'+body['order_id']).status_code,200)
    def test_bad_event(self):
        with self.assertRaises(ValueError): notification.handle_event(b'{}')

if __name__=='__main__': unittest.main()
