<h2>Routing API Endpoints</h2>

The Routing API consists of several endpoints that allow you to interact with the routing system. You can retrieve lists of routes, stops, and buses, as well as create new orders and bookings, mark routes as started or finished, and reset the routing system.

To use the API, you can send HTTP requests to the appropriate URL patterns, passing in any required parameters as needed. The API responds with JSON data, which can be easily consumed by another application.

Here, function call graphs are provided for each endpoint. These are visual representation of the functions called during the handling of the request. While there are (side) functions which are also called, but are not included in the graphs, these images aim to provide an overall understanding of what parts of the code a request goes through.

This is what a function call graph looks like for the UnverbindlicheAnfrage endpoint. **The rest of the graphs are to be found in the _/docs/images_ folder.**

![UnverbindlicheAnfrage](./images/UnverbindlicheAnfrage.png)

<h2>Communication through RabbitMQ</h2>

The Routing component communicates with our CMS Directus through the message broker RabbitMQ. Here is a short summary of how the communication happens:

1. The Routing API uses a RabbitMQ sender class (`RabbitMqSender`) to send messages to RabbitMQ.
2. The Routing API is responsible for propagating events, which indicate route-related changes, such as _RouteConfirmedIntegrationEvent_, _RouteStartedIntegrationEvent_, etc., which format the message and publish it to RabbitMQ with the appropriate routing key.
3. It also registers callback functions for different events indicating order-, bus- or stop-related changes  such as _OrderStartedIntegrationEvent_, _UpdateBusPositionIntegrationEvent_, _StopDeletedIntegrationEvent_, etc.
4. When a message is published to RabbitMQ, the corresponding callback function is triggered and processed by the API.
5. The callback functions are responsible for updating the application state and triggering further actions based on the received message (e.g., request route computation from the routing component or update the database).

This image provides an overview of the RabbitMQ structure as well as the different routing and binding keys used by the exchanges and queues.

![rabbitMqCommunication](./images/rabbitMqCommunication.png)

<h2>Database Schema</h2>

The database we use is PostgreSQL. Following tables are used:
- **Mobis_station**: represents a bus station with a unique ID, name, and community
- **Mobis_bus**: represents a bus with a unique ID, name, community, capacity, and capacity for wheelchairs. Has a ForeignKey relationship with Mobis_route.
- **Mobis_route**: represents a bus route with a unique ID, status (draft, booked, frozen, started, finished), community, and a ForeignKey relationship with Mobis_bus.
- **Mobis_node**: represents a stop on a bus route with a unique ID, map ID, departure and arrival times, and latitude and longitude coordinates. Has a ForeignKey relationship with Mobis_route and Mobis_order
- **Mobis_order**: represents an order/reservation for a bus ride with a unique ID, load (number of seats reserved), load wheelchair (number of wheelchair spaces reserved), and ForeignKey relationships with Mobis_node for hop-on and hop-off stops.

![databaseSchema](./images/databaseSchema.png){width=75% height=75%}
