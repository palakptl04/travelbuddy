# ---------------------------------------------------------------------------
# Departure cities — major Gujarat cities from which travellers depart
# ---------------------------------------------------------------------------
GUJARAT_CITIES = [
    'Ahmedabad',
    'Surat',
    'Vadodara',
    'Rajkot',
    'Gandhinagar',
    'Bhavnagar',
    'Jamnagar',
    'Junagadh',
    'Anand',
    'Bharuch',
    'Valsad',
    'Vapi',
    'Navsari',
    'Mehsana',
    'Bhuj',
    'Gandhidham',
]

# ---------------------------------------------------------------------------
# Destinations — tourist / holiday spots travellers go TO
# ---------------------------------------------------------------------------
DESTINATIONS = [
    'Dwarka',
    'Somnath',
    'Veraval',
    'Diu',
    'Saputara',
    'Statue of Unity',
    'Gir National Park',
    'Rann of Kutch',
    'Bhuj',
    'Mandvi',
    'Ahmedabad',
    'Vadodara',
    'Rajkot',
    'Mount Abu',
    'Udaipur',
    'Jaipur',
    'Mumbai',
    'Pune',
    'Goa',
    'Manali',
    'Shimla',
    'Delhi',
    'Agra',
    'Jaisalmer',
    'Jodhpur',
    'Kerala',
    'Mysuru',
    'Ooty',
    'Coorg',
]

# ---------------------------------------------------------------------------
# Choice tuples for WTForms SelectField
# ---------------------------------------------------------------------------
DEPARTURE_CITY_CHOICES = [(c, c) for c in GUJARAT_CITIES]
DESTINATION_CHOICES    = [(d, d) for d in DESTINATIONS]

# Backward-compat: full union used in older references (e.g. browse filter)
CITY_CHOICES = [(c, c) for c in sorted(set(GUJARAT_CITIES + DESTINATIONS))]

# Legacy alias kept so any existing import of NEARBY_CITIES doesn't break
NEARBY_CITIES = ['Mumbai', 'Pune', 'Udaipur', 'Mount Abu', 'Goa', 'Delhi']
