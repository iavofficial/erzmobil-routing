from pika import ConnectionParameters, BlockingConnection, PlainCredentials, exceptions, BasicProperties, DeliveryMode
import os
from _thread import start_new_thread
import logging
import threading
from functools import partial
import atexit

LOGGER = logging.getLogger('Mobis.EventBus')

HOST = os.environ.get('RABBITMQ_HOST','rabbitmq')
USER = os.environ.get('RABBITMQ_USERNAME','guest')
PASS = os.environ.get('RABBITMQ_PASSWORD','guest')
VHOST = os.environ.get('RABBITMQ_VHOST','/').replace("'", "").replace('"','')

if VHOST.lower().startswith('c:'):
    VHOST = '/'

EXCHANGE = 'busnow_event_bus'

if HOST:
    credentials = PlainCredentials(USER, PASS)
    parameters = ConnectionParameters(host=HOST,
                                      virtual_host=VHOST,
                                      credentials=credentials,
                                      heartbeat=60,
                                      blocked_connection_timeout=300, # after this, a blocked connection is closed
                                      connection_attempts=(5*60)//5, # listen for 5 minutes, then throw an error
                                      retry_delay=5)

class AsyncPublisher(threading.Thread):
    """
    Provides an asynchronous publisher for RabbitMQ. It inherits from `threading.Thread`, 
    allowing it to run the publishing process in a separate thread.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.daemon = True
        self.is_running = True
        self.name = "AsyncPublisher"

        self.connection = BlockingConnection(parameters)
        self.channel = self.connection.channel()
        self.channel.confirm_delivery()
        atexit.register(self.stop)

    def run(self):
        """
        Overrides the `threading.Thread.run()` method. This is the main loop of the thread where we continuously 
        process data events as long as the thread is running.
        """
        while self.is_running:
            self.connection.process_data_events(time_limit=1)
    
    def _publish(self, routing_key, message, exchange=EXCHANGE):
        try:
            self.channel.basic_publish(exchange=exchange,
                                       routing_key=routing_key,
                                       body=message,
                                       properties=BasicProperties(content_type='application/json',
                                                                  delivery_mode=DeliveryMode.Transient))
            LOGGER.info(f"Published {routing_key} with body: {message}")
        except exceptions.UnroutableError as error:
            LOGGER.exception(f"Message could not be confirmed: {error}")

    def publish(self, message, routing_key, exchange=EXCHANGE):
        """
        Public method used to publish messages in a thread-safe manner 
        to ensure the `_publish` function is executed within the connection's IO loops context by calling
        back into the IO loop correctly from worker threads with `add_callback_threadsafe`.
        """
        self.connection.add_callback_threadsafe(lambda: self._publish(routing_key, message, exchange))
    
    def stop(self):
        """
        Stops the running thread, processes any remaining data events and closes the connection if it's open.
        """
        self.is_running = False
        # Wait until all the data events have been processed
        self.connection.process_data_events(time_limit=1)
        if self.connection.is_open:
            self.connection.close()

class UnthreadedPublisher():
    """
    An unthreaded publisher, which opens a connection to the RabbitMQ instance. Responsible for publishing messages
    and managing the connection (e.g., creating a channel before sending a message and closing it afterwards).
    """
    def connect(self):
        return BlockingConnection(parameters=parameters)

    def create_channel(self):
        return self._connection.channel()

    def close_channel(self, channel):
        channel.close()

    def publish(self, message, routing_key, exchange=EXCHANGE):
        self._connection = self.connect()
        channel = self.create_channel()
        channel.basic_publish(exchange=exchange, 
                              routing_key=routing_key, 
                              body=message, 
                              properties=BasicProperties(content_type='text/plain', delivery_mode=1))
        LOGGER.info(f"Published {routing_key} with body: {message}")
        # self._connection.add_timeout(0, partial(self.close_channel, channel))
        self._connection.close()

class Consumer():
    """ Consumes messages from a RabbitMQ queue. Includes a dictionary of routing keys to callback functions."""

    connection = None
    channel = None
    callbacks = dict()  # routing_key: callback_function

    def __init__(self, queue_name='Busnow.Routes.API.Model.Routes'):
        self.queue_name = queue_name
    
    def run(self):
        """ Starts a background thread that runs the `run_loop` method. """
        start_new_thread(self.run_loop, ())

    def setup(self):
        """ Opens a connection to RabbitMQ, creates a channel, an exchange, and a queue and binds the que of each routing key to the `EXCHANGE`. """
        # This throws an error if no rabbitmq variables were set
        # Wait for RabbitMQ
        try:
            LOGGER.info('Trying to connect consumer to %s...', parameters)
            self.connection = BlockingConnection(parameters)
            LOGGER.info('Success!')
        except exceptions.ConnectionClosed as err:
            LOGGER.error('failed with: %s', err, exc_info=True)
            raise err
        self.channel = self.connection.channel()
        LOGGER.info(f"Created channel {self.channel}")
        self.channel.exchange_declare(exchange=EXCHANGE,
                                      exchange_type='direct')
        LOGGER.info(f"Declared exchange {EXCHANGE}")
        self.result = self.channel.queue_declare(self.queue_name, exclusive=False, durable=True)
        LOGGER.info(f"Declared queue {self.queue_name}")
        
        for key in self.callbacks:
            self.channel.queue_bind(routing_key=key,
                                    exchange=EXCHANGE,
                                    queue=self.queue_name)
            LOGGER.info(f"Bound exchange {EXCHANGE} to queue {self.queue_name} with binding key {key}")

    def tear_down(self):
        if self.channel and self.channel.is_open:
            self.channel.close()
        if self.connection and self.connection.is_open:
            self.connection.close()

    def register(self, routing_key, callback):
        """ Registers a given callback to a `routing_key`. """

        self.callbacks[routing_key] = callback
        LOGGER.info(f"Registered {callback.__name__} function to {routing_key} routing key")

    def run_loop(self):
        """
        Runs in the background thread, maintains a connection to the RabbitMQ broker and consumes incoming messages.
        """
        while True:
            try:
                self.setup()
                self.channel.basic_consume(str(self.queue_name), self._callback)
                self.channel.start_consuming()
            except exceptions.ConnectionClosed as e:
                LOGGER.error(f"Connection closed: {e}")
            except exceptions.ChannelError as e:
                LOGGER.error(f"Channel error: {e}")
            except Exception as e:
                LOGGER.exception(e)  # Log entire exception traceback for unexpected errors
            finally:
                LOGGER.info("Tearing down connection and channel")
                self.tear_down()  # Pass connection and channel for cleanup

    
    def _callback(self, ch, method, properties, body):
        """ Invokes the callback function for the routing key from the message. """

        LOGGER.info(f"Incoming message with body {body}")
        if method.routing_key not in self.callbacks:
            LOGGER.warning(f"{method.routing_key} not registered!")
        try:
            self.channel.basic_ack(delivery_tag=method.delivery_tag)
            self.callbacks[method.routing_key](ch, method, properties, body)
        except Exception as err:
            LOGGER.error('%s, key: %s', err, method.routing_key, extra={'body': body}, exc_info=True)
            
