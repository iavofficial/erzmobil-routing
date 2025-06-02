"""
 Copyright © 2025 IAV GmbH Ingenieurgesellschaft Auto und Verkehr, All Rights Reserved.
 
 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at
 
 http://www.apache.org/licenses/LICENSE-2.0
 
 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
 
 SPDX-License-Identifier: Apache-2.0
"""
from django.conf import settings
from django.conf.urls import include
from django.urls import path
from Routing_Api.Mobis.views import UnverbindlicheAnfrage as UnverbindlicheAnfrage_view, RoutendetailsAnfrageMobi as RoutendetailsAnfrageMobi_view, RoutendetailsAnfrageBusfahrer as RoutendetailsAnfrageBusfahrer_view, RouteStarted as RouteStarted_view, RouteFinished as RouteFinished_view, RoutendetailsBusId as RoutendetailsBusId_view, HealthCheck as HealthCheck_view, VerbindlicheAnfrage as VerbindlicheAnfrage_view, reset

urlpatterns = [
    path('routes/', UnverbindlicheAnfrage_view, name='UnverbindlicheAnfrage'),
    path('routes/<int:routeId>/Orders/<int:orderId>', RoutendetailsAnfrageMobi_view, name='RoutendetailsAnfrageMobi'),
    path('routes/<int:routeId>/', RoutendetailsAnfrageBusfahrer_view, name='RoutendetailsAnfrageBusfahrer'),
    path('routes/<int:routeId>/started', RouteStarted_view, name='RouteStarted'),
    path('routes/<int:routeId>/started/', RouteStarted_view, name='RouteStarted'),
    path('routes/<int:routeId>/finished', RouteFinished_view, name='RouteFinished'),
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
