from django.conf import settings
from django.conf.urls import include
from django.urls import path
from Routing_Api.Mobis.views import UnverbindlicheAnfrage as UnverbindlicheAnfrage_view, RoutendetailsAnfrageMobi as RoutendetailsAnfrageMobi_view, RoutendetailsAnfrageBusfahrer as RoutendetailsAnfrageBusfahrer_view, RouteStarted as RouteStarted_view, RouteFinished as RouteFinished_view, RoutendetailsBusId as RoutendetailsBusId_view, HealthCheck as HealthCheck_view, VerbindlicheAnfrage as VerbindlicheAnfrage_view, reset

urlpatterns = [
    path('routes/', UnverbindlicheAnfrage_view, name='UnverbindlicheAnfrage'),
    path('routes/<int:routeId>/Orders/<int:orderId>', RoutendetailsAnfrageMobi_view, name='RoutendetailsAnfrageMobi'),
    path('routes/<int:routeId>/', RoutendetailsAnfrageBusfahrer_view, name='RoutendetailsAnfrageBusfahrer'),
    path('routes/<int:routeId>/started/', RouteStarted_view, name='RouteStarted'),
    path('routes/<int:routeId>/finished/', RouteFinished_view, name='RouteFinished'),
    path('routes/buses/<int:busId>', RoutendetailsBusId_view, name='RoutendetailsBusId'),
    path('health', HealthCheck_view, name='HealthCheck'),
]

if settings.DEBUG:
    import debug_toolbar
    from Routing_Api.Mobis.serializers import Route, RouteSerializer
    from Routing_Api.Mobis.serializers import Station, StationSerializer, Bus, BusSerializer
    from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView

    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),] + [
        path('routes/', ListCreateAPIView.as_view(queryset=Route.objects.all(), serializer_class=RouteSerializer), name='route-list'),
        path('routes/book/<int:orderId>', VerbindlicheAnfrage_view, name="VerbindlicheAnfrage"),
        path('stops/', ListCreateAPIView.as_view(queryset=Station.objects.all(), serializer_class=StationSerializer), name='stop-list'),
        path('stops/<int:pk>', RetrieveUpdateDestroyAPIView.as_view(queryset=Station.objects.all(), serializer_class=StationSerializer), name='stop-list'),
        path('buses/', ListCreateAPIView.as_view(queryset=Bus.objects.all(), serializer_class=BusSerializer), name='bus-list'),
        path('buses/<int:pk>', RetrieveUpdateDestroyAPIView.as_view(queryset=Bus.objects.all(), serializer_class=BusSerializer), name='bus-list'),
        path('routes/reset/', reset, name="reset"),
    ]