from django.shortcuts import render
from . import apifunctions as API
from .models import Route, Node
from .serializers import RouteSerializer

from django.http import HttpResponse, JsonResponse
import json

from rest_framework.decorators import api_view, renderer_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from django.http import Http404, HttpResponseBadRequest
from datetime import datetime
from dateutil.tz import tzutc


# from UserMinThrottle import UserMinThrottle
import traceback
import sys

UTC = tzutc()

@api_view(['GET'])
def reset(request):
    API.reset()
    return Response(data=True)

@api_view(['GET'])
def UnverbindlicheAnfrage(request):
    
    got_startLatitude, startLatitude = API.not_float(request.GET.get('startLatitude', None))
    if not got_startLatitude:
        return Response(status=400, data={'result': False, 'reasonCode': API.GetRequestManager().INVALID_REQUEST_PARAMETER, 'reasonText': 'StartLatitude is missing.', 'alternativeTimes:': []})                
    
    got_startLongitude, startLongitude = API.not_float(request.GET.get('startLongitude', None))
    if not got_startLongitude:
        return Response(status=400, data={'result': False, 'reasonCode': API.GetRequestManager().INVALID_REQUEST_PARAMETER, 'reasonText': 'StartLongitude is missing.', 'alternativeTimes:': []})                
            
    got_stopLatitude, stopLatitude = API.not_float(request.GET.get('stopLatitude', None))
    if not got_stopLatitude:
        return Response(status=400, data={'result': False, 'reasonCode': API.GetRequestManager().INVALID_REQUEST_PARAMETER, 'reasonText': 'StopLatitude is missing.', 'alternativeTimes:': []})                
            
    got_stopLongitude, stopLongitude = API.not_float(request.GET.get('stopLongitude', None))
    if not got_stopLongitude:
        return Response(status=400, data={'result': False, 'reasonCode': API.GetRequestManager().INVALID_REQUEST_PARAMETER, 'reasonText': 'StopLongitude is missing.', 'alternativeTimes:': []})                
                
    got_time, time = API.not_time(request.GET.get('time', None))
    if not got_time:
        return Response(status=400, data={'result': False, 'reasonCode': API.GetRequestManager().INVALID_REQUEST_PARAMETER, 'reasonText': 'Time is missing.', 'alternativeTimes:': []})                
    
    got_departure, isDeparture = API.not_boolean(request.GET.get('isDeparture', None))

    if not got_departure:
        return Response(status=400, data={'result': False, 'reasonCode': API.GetRequestManager().INVALID_REQUEST_PARAMETER, 'reasonText': 'IsDeparture is missing.', 'alternativeTimes:': []})                
    
    # seats and wheelchair seats are not depending on each other in order, both can be 0, but one must be at least 1
    got_seatNumber, seatNumber = API.not_pos_integer_or_null(request.GET.get('seatNumber', '0'), upper_bound=200)
    if not got_seatNumber or seatNumber is None:
        return Response(status=400, data={'result': False, 'reasonCode': API.GetRequestManager().INVALID_REQUEST_PARAMETER, 'reasonText': 'SeatNumber is invalid, must be defined as integer >= 0.', 'alternativeTimes:': []})                
    
    got_seatNumberWheelchair, seatNumberWheelchair = API.not_pos_integer_or_null(request.GET.get('seatNumberWheelchair', '0'), upper_bound=200)
    
    if not got_seatNumberWheelchair or seatNumberWheelchair is None:
        return Response(status=400, data={'result': False, 'reasonCode': API.GetRequestManager().INVALID_REQUEST_PARAMETER, 'reasonText': 'SeatNumberWheelchair is invalid, must be defined as integer >= 0.', 'alternativeTimes:': []})        
        
    if seatNumber+seatNumberWheelchair == 0:
        return Response(status=400, data={'result': False, 'reasonCode': API.GetRequestManager().EMPTY_ORDER, 'reasonText': 'SeatNumber and seatNumberWheelchair is both 0, one value must be at least 1.', 'alternativeTimes:': []})
        
    got_routeId, routeId = API.not_pos_integer(request.GET.get('routeId', None))
    if routeId is not None and not got_routeId:        
        return Response(status=400, data={'result': False, 'reasonCode': API.GetRequestManager().INVALID_REQUEST_PARAMETER, 'reasonText': 'RouteId is invalid', 'alternativeTimes:': []})

    # should we look for alternative routing times?
    alternatives_mode=request.GET.get('suggestAlternatives', None)    
    
    try:
        return API.RouteCheck((startLatitude, startLongitude), (stopLatitude, stopLongitude),
                            time, isDeparture, seatNumber=seatNumber, wheelchairNumber=seatNumberWheelchair, routeId=routeId, alternatives_mode=alternatives_mode)
    except Exception as err:   
        print(traceback.format_exc())
        print(sys.exc_info()[2])
        return Response(status=500, data={'result': 'unknown errors when calling API', 'reasonCode': '-1', 'reasonText': traceback.format_exc(), 'alternativeTimes:': []}) # print(sys.exc_info()[2])	
		

@api_view(['GET'])
def VerbindlicheAnfrage(request, orderId):
    got_startLatitude, startLatitude = API.not_float(request.GET.get('startLatitude', None))
    if not got_startLatitude:
        raise ValidationError('startLatitude is missing.')
    got_startLongitude, startLongitude = API.not_float(request.GET.get('startLongitude', None))
    if not got_startLongitude:
        raise ValidationError('startLongitude is missing.')
    got_stopLatitude, stopLatitude = API.not_float(request.GET.get('stopLatitude', None))
    if not got_stopLatitude:
        raise ValidationError('stopLatitude is missing.')
    got_stopLongitude, stopLongitude = API.not_float(request.GET.get('stopLongitude', None))
    if not got_stopLongitude:
        raise ValidationError('stopLongitude is missing.')
    got_time, time = API.not_time(request.GET.get('time', None))
    if not got_time:
        raise ValidationError('time is missing.')
    got_departure, isDeparture = API.not_boolean(request.GET.get('isDeparture', None))
    if not got_departure:
        raise ValidationError('isDeparture is missing.')

    # seats and wheelchair seats are not depending on each other in order, both can be 0, but one must be at least 1
    got_seatNumber, seatNumber = API.not_pos_integer_or_null(request.GET.get('seatNumber', '0'), upper_bound=200)
    if not got_seatNumber or seatNumber is None:
        raise ValidationError('seatNumber is invalid, must be defined as integer >= 0.')
    got_seatNumberWheelchair, seatNumberWheelchair = API.not_pos_integer_or_null(request.GET.get('seatNumberWheelchair', '0'), upper_bound=200)
    if not got_seatNumberWheelchair or seatNumberWheelchair is None:
        raise ValidationError('seatNumberWheelchair is invalid, must be defined as integer >= 0.')
    if seatNumber+seatNumberWheelchair == 0:
        raise ValidationError('seatNumber and seatNumberWheelchair is both 0, one value must be at least 1.')

    got_routeId, routeId = API.not_pos_integer(request.GET.get('routeId', None))
    if routeId is not None and not got_routeId:
        raise ValidationError('routeId is invalid.')
    
    return API.RouteRequest((startLatitude, startLongitude), (stopLatitude, stopLongitude),
                            time, isDeparture, seatNumber=seatNumber, wheelchairNumber=seatNumberWheelchair, routeId=routeId, orderId=orderId)

@api_view(['GET'])
def RoutendetailsAnfrageMobi(request, routeId, orderId=None):
    got_orderId, orderId = API.not_pos_integer(orderId)
    if orderId is not None and not got_orderId:
        raise ValidationError('orderId is invalid.')
    got_routeId, routeId = API.not_pos_integer(routeId)
    if routeId is not None and not got_routeId:
        raise ValidationError('routeId is invalid.')

    # enable requesting gps coords
    got_gps_requested, gps_requested = API.not_boolean(request.GET.get('gps', None))

    # print('RoutendetailsAnfrageMobi')
    # print(request.GET.get('gps', None))
    # print(gps_requested)
    
    if gps_requested == True:
        return Response(data=API.order_details_with_gps(routeId, orderId))
    else:
        return Response(data=API.order_details(routeId, orderId))

@api_view(['GET'])
def RoutendetailsAnfrageBusfahrer(request, routeId):
    got_routeId, routeId = API.not_pos_integer(routeId)
    if routeId is not None and not got_routeId:
        raise ValidationError('routeId is invalid.')

    got_gps_requested, gps_requested = API.not_boolean(request.GET.get('gps', None))

    # print('RoutendetailsAnfrageBusfahrer')
    # print(request.GET.get('gps', None))
    # print(gps_requested)

    if gps_requested == True:
        return Response(data=API.driver_details_with_gps(routeId))
    else:
        return Response(data=API.driver_details(routeId))

@api_view(['GET'])
def RoutendetailsBusId(request, busId):
    got_busId, busId = API.not_pos_integer(busId)
    if busId is not None and not got_busId:
        raise ValidationError('busId is invalid.')
    got_t_min, t_min = API.not_time(request.GET.get('timeMin', None))
    got_t_max, t_max = API.not_time(request.GET.get('timeMax', None))
    if not t_min:
        t_min = datetime.now(UTC)

    return Response(data=API.driver_details_busId(busId, timeMin=t_min, timeMax=t_max))

@api_view(['PUT'])
def RouteStarted(request, routeId):
    got_routeId, routeId = API.not_pos_integer(routeId)
    if routeId is not None and not got_routeId:
        raise ValidationError('routeId is invalid.')
    return API.RouteStarted(routeId)
@api_view(['PUT'])
def RouteFinished(request, routeId):
    got_routeId, routeId = API.not_pos_integer(routeId)
    if routeId is not None and not got_routeId:
        raise ValidationError('routeId is invalid.')
    return API.RouteFinished(routeId)

def HealthCheck(request):
    return HttpResponse('', status=200)

# error views:
def handler500(request, *args, **argv):
    context = {
        'status': 500,
        'message': 'server error',
        }
    return JsonResponse(context, status=500)

def handler404(request, exception, template_name="404.html"):
    context = {
        'status': 404,
        'message': 'not found',
        }
    return JsonResponse(context, status=404)