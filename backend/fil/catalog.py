"""Competition catalogue: what we try to cover and which provider can supply each competition.

`fd_uk` = football-data.co.uk division code, `fd_uk_new` = its "extra leagues" code,
`tsdb` = TheSportsDB league id, `fdorg` = football-data.org competition code,
`intl` = tournament name in the international-results dataset.
"""

COMPETITIONS = [
    # --- UEFA club competitions
    dict(code="UCL", name="UEFA Champions League", country="Europe", region="Europe", kind="cup", priority=1,
         sources={"tsdb": "4480", "fdorg": "CL"}),
    dict(code="UEL", name="UEFA Europa League", country="Europe", region="Europe", kind="cup", priority=1,
         sources={"tsdb": "4481"}),
    dict(code="UECL", name="UEFA Conference League", country="Europe", region="Europe", kind="cup", priority=1,
         sources={"tsdb": "5071"}),
    # --- European domestic (football-data.co.uk main files)
    dict(code="ENG1", name="Premier League", country="England", region="Europe", priority=1, sources={"fd_uk": "E0", "tsdb": "4328", "fdorg": "PL"}),
    dict(code="ENG2", name="Championship", country="England", region="Europe", priority=2, sources={"fd_uk": "E1", "tsdb": "4329", "fdorg": "ELC"}),
    dict(code="ENG3", name="League One", country="England", region="Europe", priority=3, sources={"fd_uk": "E2"}),
    dict(code="ENG4", name="League Two", country="England", region="Europe", priority=3, sources={"fd_uk": "E3"}),
    dict(code="ENG5", name="National League", country="England", region="Europe", priority=3, sources={"fd_uk": "EC"}),
    dict(code="ITA1", name="Serie A", country="Italy", region="Europe", priority=1, sources={"fd_uk": "I1", "tsdb": "4332", "fdorg": "SA"}),
    dict(code="ITA2", name="Serie B", country="Italy", region="Europe", priority=2, sources={"fd_uk": "I2"}),
    dict(code="ESP1", name="La Liga", country="Spain", region="Europe", priority=1, sources={"fd_uk": "SP1", "tsdb": "4335", "fdorg": "PD"}),
    dict(code="ESP2", name="Segunda División", country="Spain", region="Europe", priority=2, sources={"fd_uk": "SP2"}),
    dict(code="GER1", name="Bundesliga", country="Germany", region="Europe", priority=1, sources={"fd_uk": "D1", "tsdb": "4331", "fdorg": "BL1"}),
    dict(code="GER2", name="2. Bundesliga", country="Germany", region="Europe", priority=2, sources={"fd_uk": "D2"}),
    dict(code="FRA1", name="Ligue 1", country="France", region="Europe", priority=1, sources={"fd_uk": "F1", "tsdb": "4334", "fdorg": "FL1"}),
    dict(code="FRA2", name="Ligue 2", country="France", region="Europe", priority=2, sources={"fd_uk": "F2"}),
    dict(code="POR1", name="Primeira Liga", country="Portugal", region="Europe", priority=1, sources={"fd_uk": "P1", "fdorg": "PPL"}),
    dict(code="NED1", name="Eredivisie", country="Netherlands", region="Europe", priority=1, sources={"fd_uk": "N1", "fdorg": "DED"}),
    dict(code="BEL1", name="Belgian Pro League", country="Belgium", region="Europe", priority=1, sources={"fd_uk": "B1"}),
    dict(code="TUR1", name="Süper Lig", country="Turkey", region="Europe", priority=1, sources={"fd_uk": "T1"}),
    dict(code="SCO1", name="Scottish Premiership", country="Scotland", region="Europe", priority=1, sources={"fd_uk": "SC0"}),
    dict(code="SCO2", name="Scottish Championship", country="Scotland", region="Europe", priority=3, sources={"fd_uk": "SC1"}),
    dict(code="SCO3", name="Scottish League One", country="Scotland", region="Europe", priority=3, sources={"fd_uk": "SC2"}),
    dict(code="SCO4", name="Scottish League Two", country="Scotland", region="Europe", priority=3, sources={"fd_uk": "SC3"}),
    dict(code="GRE1", name="Super League Greece", country="Greece", region="Europe", priority=2, sources={"fd_uk": "G1"}),
    # --- football-data.co.uk "extra" leagues
    dict(code="AUT1", name="Austrian Bundesliga", country="Austria", region="Europe", priority=2, sources={"fd_uk_new": "AUT", "fd_uk_league": "Austria|Bundesliga"}),
    dict(code="SUI1", name="Swiss Super League", country="Switzerland", region="Europe", priority=2, sources={"fd_uk_new": "SWZ", "fd_uk_league": "Switzerland|Super League"}),
    dict(code="DEN1", name="Danish Superliga", country="Denmark", region="Europe", priority=2, sources={"fd_uk_new": "DNK", "fd_uk_league": "Denmark|Superliga"}),
    dict(code="NOR1", name="Eliteserien", country="Norway", region="Europe", priority=2, sources={"fd_uk_new": "NOR", "fd_uk_league": "Norway|Eliteserien"}),
    dict(code="SWE1", name="Allsvenskan", country="Sweden", region="Europe", priority=2, sources={"fd_uk_new": "SWE", "fd_uk_league": "Sweden|Allsvenskan"}),
    dict(code="POL1", name="Ekstraklasa", country="Poland", region="Europe", priority=2, sources={"fd_uk_new": "POL", "fd_uk_league": "Poland|Ekstraklasa"}),
    dict(code="ROU1", name="Romanian Superliga", country="Romania", region="Europe", priority=2, sources={"fd_uk_new": "ROU", "fd_uk_league": "Romania|Superliga"}),
    dict(code="FIN1", name="Veikkausliiga", country="Finland", region="Europe", priority=3, sources={"fd_uk_new": "FIN", "fd_uk_league": "Finland|Veikkausliiga"}),
    dict(code="IRL1", name="League of Ireland Premier", country="Ireland", region="Europe", priority=3, sources={"fd_uk_new": "IRL", "fd_uk_league": "Ireland|Premier Division"}),
    dict(code="BRA1", name="Brasileirão Série A", country="Brazil", region="Americas", priority=1, sources={"fd_uk_new": "BRA", "fd_uk_league": "Brazil|Serie A", "fdorg": "BSA"}),
    dict(code="ARG1", name="Liga Profesional Argentina", country="Argentina", region="Americas", priority=1, sources={"fd_uk_new": "ARG", "fd_uk_league": "Argentina|Liga Profesional"}),
    dict(code="MEX1", name="Liga MX", country="Mexico", region="Americas", priority=2, sources={"fd_uk_new": "MEX", "fd_uk_league": "Mexico|Liga MX"}),
    dict(code="USA1", name="MLS", country="USA", region="Americas", priority=2, sources={"fd_uk_new": "USA", "fd_uk_league": "USA|MLS"}),
    dict(code="JPN1", name="J1 League", country="Japan", region="Asia", priority=2, sources={"fd_uk_new": "JPN", "fd_uk_league": "Japan|J1 League"}),
    dict(code="CHN1", name="Chinese Super League", country="China", region="Asia", priority=3, sources={"fd_uk_new": "CHN", "fd_uk_league": "China|Super League"}),
    # --- African football
    dict(code="CAFCL", name="CAF Champions League", country="Africa", region="Africa", kind="cup", priority=1, sources={"tsdb": "4720"}),
    dict(code="CAFCC", name="CAF Confederation Cup", country="Africa", region="Africa", kind="cup", priority=1, sources={"tsdb": "4721"}),
    dict(code="EGY1", name="Egyptian Premier League", country="Egypt", region="Africa", priority=1, sources={"tsdb": "4829"}),
    dict(code="MAR1", name="Botola Pro", country="Morocco", region="Africa", priority=1, sources={"tsdb": "4520"}),
    dict(code="RSA1", name="South African Premiership", country="South Africa", region="Africa", priority=1, sources={"tsdb": "4802"}),
    dict(code="TUN1", name="Tunisian Ligue Professionnelle 1", country="Tunisia", region="Africa", priority=1, sources={"tsdb": "4828"}),
    # --- national teams
    dict(code="AFCON", name="Africa Cup of Nations (+qualifiers)", country="Africa", region="International", kind="international", priority=1,
         sources={"intl": ["African Cup of Nations", "African Cup of Nations qualification"]}),
    dict(code="WCQ", name="FIFA World Cup (+qualifiers)", country="World", region="International", kind="international", priority=1,
         sources={"intl": ["FIFA World Cup", "FIFA World Cup qualification"], "fdorg": "WC"}),
    dict(code="UNL", name="UEFA Nations League / Euro", country="Europe", region="International", kind="international", priority=2,
         sources={"intl": ["UEFA Nations League", "UEFA Euro", "UEFA Euro qualification"], "fdorg": "EC"}),
    dict(code="INTFR", name="International Friendlies", country="World", region="International", kind="international", priority=3,
         sources={"intl": ["Friendly"]}),
    dict(code="COPA", name="Copa América / CONMEBOL", country="South America", region="International", kind="international", priority=2,
         sources={"intl": ["Copa América"]}),
    dict(code="ASIAN", name="AFC Asian Cup (+qualifiers)", country="Asia", region="International", kind="international", priority=2,
         sources={"intl": ["AFC Asian Cup", "AFC Asian Cup qualification"]}),
]

BY_CODE = {c["code"]: c for c in COMPETITIONS}
FD_UK_DIV = {c["sources"]["fd_uk"]: c["code"] for c in COMPETITIONS if "fd_uk" in c["sources"]}
FD_UK_NEW = {c["sources"]["fd_uk_new"]: c["code"] for c in COMPETITIONS if "fd_uk_new" in c["sources"]}
FD_UK_LEAGUE = {c["sources"]["fd_uk_league"]: c["code"] for c in COMPETITIONS if "fd_uk_league" in c["sources"]}
INTL_TOURNAMENT = {t: c["code"] for c in COMPETITIONS for t in c["sources"].get("intl", [])}
