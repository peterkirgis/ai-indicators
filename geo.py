"""Normalize free-text comment locations to US state abbreviations."""

import re

STATE_ABBREVS = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'DC',
}

STATE_NAMES = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR',
    'california': 'CA', 'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE',
    'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID',
    'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS',
    'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
    'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS',
    'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV',
    'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY',
    'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK',
    'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
    'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT',
    'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV',
    'wisconsin': 'WI', 'wyoming': 'WY', 'district of columbia': 'DC',
}

# Major US cities -> state. Lowercase keys for case-insensitive matching.
CITY_TO_STATE = {
    # New York
    'nyc': 'NY', 'new york city': 'NY', 'manhattan': 'NY', 'brooklyn': 'NY',
    'bronx': 'NY', 'queens': 'NY', 'staten island': 'NY', 'harlem': 'NY',
    'long island': 'NY', 'buffalo': 'NY', 'rochester': 'NY', 'albany': 'NY',
    'ithaca': 'NY', 'syracuse': 'NY',
    # California
    'san francisco': 'CA', 'sf': 'CA', 'bay area': 'CA', 'oakland': 'CA',
    'los angeles': 'CA', 'la': 'CA', 'san diego': 'CA', 'sacramento': 'CA',
    'san jose': 'CA', 'berkeley': 'CA', 'palo alto': 'CA', 'silicon valley': 'CA',
    'cali': 'CA', 'santa monica': 'CA', 'pasadena': 'CA', 'santa barbara': 'CA',
    'santa cruz': 'CA', 'irvine': 'CA', 'fresno': 'CA', 'long beach': 'CA',
    'marin county': 'CA',
    # Illinois
    'chicago': 'IL', 'evanston': 'IL',
    # Washington
    'seattle': 'WA', 'tacoma': 'WA', 'olympia': 'WA', 'bellevue': 'WA',
    # Massachusetts
    'boston': 'MA', 'cambridge': 'MA', 'somerville': 'MA', 'amherst': 'MA',
    'northampton': 'MA', 'worcester': 'MA',
    # Pennsylvania
    'philadelphia': 'PA', 'philly': 'PA', 'pittsburgh': 'PA',
    # Texas
    'houston': 'TX', 'austin': 'TX', 'dallas': 'TX', 'san antonio': 'TX',
    'fort worth': 'TX',
    # DC area
    'washington dc': 'DC', 'washington d.c.': 'DC', 'washington, d.c.': 'DC',
    'dc': 'DC', 'd.c.': 'DC',
    # Georgia
    'atlanta': 'GA', 'savannah': 'GA',
    # Minnesota
    'minneapolis': 'MN', 'st. paul': 'MN', 'saint paul': 'MN',
    # Colorado
    'denver': 'CO', 'boulder': 'CO',
    # Oregon
    'portland': 'OR', 'eugene': 'OR',
    # Arizona
    'phoenix': 'AZ', 'tucson': 'AZ', 'scottsdale': 'AZ',
    # Maryland
    'baltimore': 'MD', 'bethesda': 'MD', 'silver spring': 'MD',
    # Florida
    'miami': 'FL', 'orlando': 'FL', 'tampa': 'FL', 'jacksonville': 'FL',
    'st. petersburg': 'FL', 'fort lauderdale': 'FL', 'naples': 'FL',
    'sarasota': 'FL',
    # Michigan
    'detroit': 'MI', 'ann arbor': 'MI', 'grand rapids': 'MI',
    # North Carolina
    'charlotte': 'NC', 'raleigh': 'NC', 'durham': 'NC', 'chapel hill': 'NC',
    'asheville': 'NC',
    # Ohio
    'cleveland': 'OH', 'columbus': 'OH', 'cincinnati': 'OH',
    # Virginia
    'arlington': 'VA', 'richmond': 'VA', 'alexandria': 'VA',
    'charlottesville': 'VA', 'norfolk': 'VA',
    # Connecticut
    'new haven': 'CT', 'hartford': 'CT', 'stamford': 'CT', 'greenwich': 'CT',
    # New Jersey
    'jersey city': 'NJ', 'hoboken': 'NJ', 'princeton': 'NJ', 'newark': 'NJ',
    # Missouri
    'st. louis': 'MO', 'saint louis': 'MO', 'kansas city': 'MO',
    # Tennessee
    'nashville': 'TN', 'memphis': 'TN', 'knoxville': 'TN',
    # Wisconsin
    'milwaukee': 'WI', 'madison': 'WI',
    # Louisiana
    'new orleans': 'LA',
    # Hawaii
    'honolulu': 'HI',
    # Nevada
    'las vegas': 'NV', 'reno': 'NV',
    # New Mexico
    'albuquerque': 'NM', 'santa fe': 'NM',
    # Indiana
    'indianapolis': 'IN',
    # Iowa
    'des moines': 'IA', 'iowa city': 'IA',
    # Kentucky
    'louisville': 'KY', 'lexington': 'KY',
    # Variants and informal names
    'upstate ny': 'NY', 'upstate new york': 'NY', 'uws': 'NY', 'ues': 'NY',
    'west village': 'NY', 'upper west side': 'NY', 'binghamton': 'NY',
    'sf bay area': 'CA', 'socal': 'CA', 'norcal': 'CA', 'nocal': 'CA',
    'northern california': 'CA', 'southern california': 'CA',
    'joshua tree': 'CA', 'marin': 'CA',
    'portland or': 'OR', 'portland oregon': 'OR',
    'washington state': 'WA',
    'cape cod': 'MA',
    'maui': 'HI', 'kauai': 'HI',
    'oklahoma city': 'OK',
    # New Hampshire
    'concord': 'NH',
    # Vermont
    'burlington': 'VT',
    # Rhode Island
    'providence': 'RI',
    # Maine
    'portland, maine': 'ME',
    # Utah
    'salt lake city': 'UT',
    # Nebraska
    'omaha': 'NE',
    # Alaska
    'anchorage': 'AK',
    # South Carolina
    'charleston': 'SC',
}

# Known international locations -> "non-us"
INTERNATIONAL = {
    'canada', 'toronto', 'montreal', 'vancouver', 'ottawa', 'calgary',
    'uk', 'united kingdom', 'england', 'london', 'britain', 'scotland',
    'france', 'paris', 'germany', 'berlin', 'munich',
    'australia', 'sydney', 'melbourne',
    'japan', 'tokyo', 'india', 'mexico', 'mexico city',
    'italy', 'rome', 'spain', 'madrid', 'barcelona',
    'netherlands', 'amsterdam', 'switzerland', 'zurich', 'geneva',
    'sweden', 'stockholm', 'norway', 'oslo', 'denmark', 'copenhagen',
    'ireland', 'dublin', 'belgium', 'brussels',
    'brazil', 'china', 'beijing', 'shanghai', 'hong kong', 'singapore',
    'south korea', 'seoul', 'taiwan', 'israel', 'tel aviv',
    'new zealand', 'auckland', 'wellington',
    'europe', 'asia', 'africa', 'south america',
    'the netherlands', 'wien', 'vienna', 'prague',
    'ontario', 'british columbia', 'quebec', 'alberta',
    'bangkok', 'thailand', 'philippines', 'vietnam',
    'greece', 'athens', 'portugal', 'lisbon', 'finland', 'helsinki',
    'poland', 'warsaw', 'austria', 'hungary', 'budapest',
    'russia', 'moscow', 'ukraine', 'turkey', 'istanbul',
    'costa rica', 'colombia', 'argentina', 'buenos aires', 'chile',
    'south africa', 'nigeria', 'kenya', 'egypt',
}

# Junk / ambiguous entries that should not map to anything
JUNK = {
    'usa', 'us', 'u.s.', 'u.s.a.', 'united states', 'america',
    'earth', 'here', 'somewhere', 'home', 'nowhere', 'everywhere',
    'the internet', 'online', 'the world', 'planet earth',
    '.', 'underfoot', 'the new york times', 'orbis tertius',
    'glenbard west', 'glenbard west high school', 'redacted',
    'around', 'world', 'left coast', 'right here',
    # US regions — can't resolve to a single state
    'midwest', 'new england', 'pnw', 'pacific nw', 'pacific northwest',
    'east coast', 'west coast', 'out west', 'upstate', 'northeast',
    'southeast', 'southwest', 'south', 'north',
}

STATE_FIPS = {
    'AL': '01', 'AK': '02', 'AZ': '04', 'AR': '05', 'CA': '06', 'CO': '08',
    'CT': '09', 'DE': '10', 'DC': '11', 'FL': '12', 'GA': '13', 'HI': '15',
    'ID': '16', 'IL': '17', 'IN': '18', 'IA': '19', 'KS': '20', 'KY': '21',
    'LA': '22', 'ME': '23', 'MD': '24', 'MA': '25', 'MI': '26', 'MN': '27',
    'MS': '28', 'MO': '29', 'MT': '30', 'NE': '31', 'NV': '32', 'NH': '33',
    'NJ': '34', 'NM': '35', 'NY': '36', 'NC': '37', 'ND': '38', 'OH': '39',
    'OK': '40', 'OR': '41', 'PA': '42', 'RI': '44', 'SC': '45', 'SD': '46',
    'TN': '47', 'TX': '48', 'UT': '49', 'VT': '50', 'VA': '51', 'WA': '53',
    'WV': '54', 'WI': '55', 'WY': '56',
}

STATE_FULL_NAMES = {v: k.title() for k, v in STATE_NAMES.items()}

# % adults 25+ with bachelor's degree or higher, by state
# Source: US Census Bureau, American Community Survey 2023 1-year estimates (Table S1501)
BACHELORS_PCT = {
    'AL': 27.5, 'AK': 30.8, 'AZ': 31.5, 'AR': 24.4, 'CA': 35.8, 'CO': 42.7,
    'CT': 40.4, 'DE': 34.2, 'DC': 62.5, 'FL': 32.3, 'GA': 33.1, 'HI': 34.0,
    'ID': 30.0, 'IL': 36.1, 'IN': 28.4, 'IA': 30.3, 'KS': 34.0, 'KY': 26.1,
    'LA': 25.3, 'ME': 34.0, 'MD': 41.3, 'MA': 45.8, 'MI': 30.6, 'MN': 37.3,
    'MS': 23.2, 'MO': 30.8, 'MT': 33.4, 'NE': 33.1, 'NV': 26.1, 'NH': 38.7,
    'NJ': 41.2, 'NM': 28.9, 'NY': 38.1, 'NC': 33.4, 'ND': 31.0, 'OH': 29.8,
    'OK': 27.0, 'OR': 35.4, 'PA': 34.0, 'RI': 35.4, 'SC': 29.6, 'SD': 30.3,
    'TN': 29.3, 'TX': 32.0, 'UT': 36.0, 'VT': 40.3, 'VA': 40.9, 'WA': 38.4,
    'WV': 22.0, 'WI': 31.5, 'WY': 28.5,
}

# GDP per capita 2023 (USD), Bureau of Economic Analysis
GDP_PER_CAPITA = {
    'AL': 52806, 'AK': 73205, 'AZ': 60283, 'AR': 49873, 'CA': 91905, 'CO': 82247,
    'CT': 88741, 'DE': 80205, 'DC': 236447, 'FL': 62016, 'GA': 63667, 'HI': 67345,
    'ID': 54284, 'IL': 75854, 'IN': 61181, 'IA': 65288, 'KS': 63887, 'KY': 53463,
    'LA': 56674, 'ME': 57996, 'MD': 71842, 'MA': 100261, 'MI': 56860, 'MN': 72275,
    'MS': 42411, 'MO': 57345, 'MT': 55614, 'NE': 70658, 'NV': 62197, 'NH': 73974,
    'NJ': 77883, 'NM': 53135, 'NY': 90956, 'NC': 60021, 'ND': 75899, 'OH': 59786,
    'OK': 55020, 'OR': 65166, 'PA': 69590, 'RI': 63620, 'SC': 52689, 'SD': 66336,
    'TN': 60331, 'TX': 71166, 'UT': 65498, 'VT': 60437, 'VA': 72061, 'WA': 86265,
    'WV': 44709, 'WI': 62587, 'WY': 70783,
}

_CITY_ST_RE = re.compile(r',\s*([A-Z]{2})\s*$')


def normalize_location(raw: str) -> str | None:
    """Normalize a free-text location to a US state abbreviation.

    Returns:
        Two-letter state code (e.g. "CA") for US locations,
        "non-us" for international locations,
        None if unmappable.
    """
    if not raw:
        return None

    stripped = raw.strip()
    lower = stripped.lower()

    # Junk
    if lower in JUNK:
        return None

    # Exact state abbreviation (case-insensitive)
    upper = stripped.upper()
    if upper in STATE_ABBREVS:
        return upper

    # Exact state name
    if lower in STATE_NAMES:
        return STATE_NAMES[lower]

    # "City, ST" pattern (e.g. "Portland, OR", "Austin, TX")
    m = _CITY_ST_RE.search(stripped)
    if m and m.group(1) in STATE_ABBREVS:
        return m.group(1)

    # Known US city
    if lower in CITY_TO_STATE:
        return CITY_TO_STATE[lower]

    # International
    if lower in INTERNATIONAL:
        return 'non-us'

    # "City, N.Y." or "City, N.Y" style (dotted abbreviations)
    dot_match = re.search(r',\s*([A-Z]\.[A-Z]\.?)\s*$', stripped)
    if dot_match:
        de_dotted = dot_match.group(1).replace('.', '')
        if de_dotted in STATE_ABBREVS:
            return de_dotted

    # Try partial: "City, State" where state is a full name
    if ',' in stripped:
        parts = [p.strip() for p in stripped.split(',')]
        last = parts[-1].lower()
        if last in STATE_NAMES:
            return STATE_NAMES[last]
        if last.upper() in STATE_ABBREVS:
            return last.upper()
        # Check if last part is a country
        if last in INTERNATIONAL:
            return 'non-us'

    return None
