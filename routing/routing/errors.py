class DuplicatedOrder(Exception):
    '''Raised when order_id already exists.'''
    pass

class MalformedMessage(Exception):
    '''Raise on missing key in message'''
    pass

class CommunityConflict(Exception):
    '''Raise on non-matching communities'''
    def __init__(self, message="No community available in the area."):
        self.message = message
        super().__init__(self.message)

class SameStop(Exception):
    '''Raise if start and destination point to the same bus stop'''
    def __init__(self, message = "Start and destination are the same or too close."):
        self.message = message
        super().__init__(self.message)  

class NoStop(Exception):
    '''Raise if no bus stop could be found near the requested location'''
    def __init__(self, message = "No matching bus stop for start or destination found."):
        self.message = message
        super().__init__(self.message)

class NoBuses(Exception):
    '''Raise if no bus resources are available'''
    def __init__(self, message = "No buses available in time window."):
        self.message = message
        super().__init__(self.message)

class NoBusesDueToBlocker(Exception):
    '''Raise if no bus resources are available due to blocked times'''
    def __init__(self, message = "No buses available in time window due to time blocker."):
        self.message = message
        super().__init__(self.message)

class BusesTooSmall(Exception):
    '''Raise if bus capa is too small'''
    def __init__(self, message = "No buses available with sufficient capacity."):
        self.message = message
        super().__init__(self.message)

class InvalidTime(Exception):
    '''Raise if any time slot within request or solution lies in the past.'''
    def __init__(self, message="The departure/destination time is in the past."):
        self.message = message
        super().__init__(self.message)

class InvalidTime2(Exception):
    '''Raise if any time slot within request or solution lies too far away in the future.'''
    def __init__(self, message="The departure/destination time is too far away in the future."):
        self.message = message
        super().__init__(self.message)

class NoRouteException(Exception):
    """Return this if no routing solution could be reached with the given constraints."""
    def __init__(self, message="The optimizer cannot find an appropriate solution fitting boundaries."):
        self.message = message
        super().__init__(self.message)

class NoRouteExceptionInternalError(Exception):
    """Return this if no routing solution could be reached due to internal error."""
    def __init__(self, message="The optimizer cannot find a solution due to internal error."):
        self.message = message
        super().__init__(self.message)