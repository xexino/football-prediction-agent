# UEFA team identity — dry-run report (nothing applied)

* "Europe" teams: **137**
* Proposed merges: **56** (curated 5, exact 50, fuzzy 1)
* Fixture columns that would be re-pointed: **1131**
* Ambiguous (several domestic candidates, never merged automatically): **0**
* Unmatched (no domestic twin in our leagues — clubs from countries we don't cover): **81**
* Conflicts — two Europe ids onto one domestic id: **1**; same team twice on one date after merge: **3**
* Club/national entities sharing one id: **2**

Apply only after: (1) a person reviews every `curated`/`fuzzy` row, (2) a domestic walk-forward re-backtest with the merged ids shows no regression, (3) a UEFA prediction path exists (Engine A fits Dixon-Coles only for domestic leagues). The merge is journaled in `team_merges` and fully reversible.

## Proposed merges

| Europe id | UEFA name | → domestic id | Domestic name | Country | Method | Conf. | Fixtures |
|---|---|---|---|---|---|---|---|
| 1313 | Ajax | 346 | Ajax | Netherlands | exact | 1.0 | 8 |
| 1289 | Antwerp FC | 372 | Antwerp | Belgium | exact | 1.0 | 6 |
| 1258 | Arsenal | 3 | Arsenal | England | exact | 1.0 | 47 |
| 1251 | Aston Villa | 14 | Aston Villa | England | exact | 1.0 | 20 |
| 1306 | Atalanta | 137 | Atalanta | Italy | exact | 1.0 | 22 |
| 1272 | Atleti | 195 | Ath Madrid | Spain | curated | 1.0 | 52 |
| 1269 | Barça | 192 | Barcelona | Spain | curated | 1.0 | 44 |
| 1282 | Bayern | 229 | Bayern Munich | Germany | curated | 1.0 | 48 |
| 857 | Bodø/Glimt | 537 | Bodo/Glimt | Norway | fuzzy | 0.947 | 20 |
| 1299 | Bologna | 144 | Bologna | Italy | exact | 1.0 | 8 |
| 1293 | Braga | 315 | Sp Braga | Portugal | exact | 1.0 | 6 |
| 1304 | Brest | 276 | Brest | France | exact | 1.0 | 10 |
| 1287 | Celtic | 414 | Celtic | Scotland | exact | 1.0 | 16 |
| 1314 | Chelsea | 17 | Chelsea | England | exact | 1.0 | 10 |
| 1273 | Club Brugge | 376 | Club Brugge | Belgium | exact | 1.0 | 30 |
| 1317 | Como | 148 | Como | Italy | exact | 1.0 | 1 |
| 1256 | Como 1907 | 148 | Como | Italy | curated | 1.0 | 8 |
| 1259 | Dortmund | 240 | Dortmund | Germany | exact | 1.0 | 45 |
| 1278 | Fenerbahçe | 400 | Fenerbahce | Turkey | exact | 1.0 | 8 |
| 1264 | Feyenoord | 354 | Feyenoord | Netherlands | exact | 1.0 | 26 |
| 1315 | Frankfurt | 244 | Ein Frankfurt | Germany | exact | 1.0 | 8 |
| 1250 | Galatasaray | 393 | Galatasaray | Turkey | exact | 1.0 | 26 |
| 1301 | Girona | 182 | Girona | Spain | exact | 1.0 | 8 |
| 1275 | Inter | 132 | Inter | Italy | exact | 1.0 | 41 |
| 1297 | Juventus | 141 | Juventus | Italy | exact | 1.0 | 20 |
| 1291 | København | 515 | FC Copenhagen | Denmark | curated | 1.0 | 16 |
| 1286 | Lazio | 139 | Lazio | Italy | exact | 1.0 | 8 |
| 1302 | Leverkusen | 234 | Leverkusen | Germany | exact | 1.0 | 22 |
| 1281 | Lille | 271 | Lille | France | exact | 1.0 | 18 |
| 1274 | Liverpool | 18 | Liverpool | England | exact | 1.0 | 30 |
| 1262 | Man City | 2 | Man City | England | exact | 1.0 | 38 |
| 1271 | Man United | 19 | Man United | England | exact | 1.0 | 14 |
| 1310 | Marseille | 272 | Marseille | France | exact | 1.0 | 8 |
| 1283 | Milan | 145 | Milan | Italy | exact | 1.0 | 16 |
| 1303 | Monaco | 279 | Monaco | France | exact | 1.0 | 20 |
| 1263 | Napoli | 129 | Napoli | Italy | exact | 1.0 | 24 |
| 1284 | Newcastle | 13 | Newcastle | England | exact | 1.0 | 18 |
| 1311 | Olympiakos | 465 | Olympiakos | Greece | exact | 1.0 | 10 |
| 1279 | PSG | 274 | Paris SG | France | exact | 1.0 | 54 |
| 1255 | PSV | 342 | PSV Eindhoven | Netherlands | exact | 1.0 | 36 |
| 1265 | Porto | 330 | Porto | Portugal | exact | 1.0 | 16 |
| 1260 | RB Leipzig | 235 | RB Leipzig | Germany | exact | 1.0 | 24 |
| 1261 | RC Lens | 277 | Lens | France | exact | 1.0 | 14 |
| 1253 | Real Betis | 190 | Betis | Spain | exact | 1.0 | 8 |
| 1254 | Real Madrid | 186 | Real Madrid | Spain | exact | 1.0 | 49 |
| 1294 | Real Sociedad | 181 | Sociedad | Spain | exact | 1.0 | 8 |
| 1280 | Roma | 134 | Roma | Italy | exact | 1.0 | 8 |
| 1295 | SL Benfica | 332 | Benfica | Portugal | exact | 1.0 | 28 |
| 1292 | Sevilla FC | 179 | Sevilla | Spain | exact | 1.0 | 6 |
| 1270 | Sporting CP | 321 | Sp Lisbon | Portugal | exact | 1.0 | 30 |
| 1305 | Sturm Graz | 481 | Sturm Graz | Austria | exact | 1.0 | 8 |
| 1276 | Stuttgart | 236 | Stuttgart | Germany | exact | 1.0 | 16 |
| 1309 | Tottenham | 16 | Tottenham | England | exact | 1.0 | 10 |
| 1290 | Union Berlin | 242 | Union Berlin | Germany | exact | 1.0 | 6 |
| 1267 | Villarreal | 189 | Villarreal | Spain | exact | 1.0 | 16 |
| 1285 | Young Boys | 493 | Young Boys | Switzerland | exact | 1.0 | 14 |

## Ambiguous (0)

none

## Conflicts (same target) (1)

| domestic_id | europe_ids |
|---|---|
| 148 | [1317, 1256] |

## Date clashes after merge (3)

| team_id | date | fixtures |
|---|---|---|
| 195 | 2026-01-21 | [58708, 58711] |
| 148 | 2026-11-24 | [56159, 58829] |
| 195 | 2026-01-28 | [58725, 58726] |

## Club/national mixed ids (2)

| team_id | name | club_fixtures | national_fixtures |
|---|---|---|---|
| 217 | Andorra | 98 | 102 |
| 279 | Monaco | 136 | 1 |

## Unmatched (81)

| europe_id | name | fixtures |
|---|---|---|
| 1318 | AEK Athens | 1 |
| 879 | Alashkert | 1 |
| 861 | Aluminij | 2 |
| 833 | Ararat-Armenia | 2 |
| 897 | Astana | 1 |
| 846 | Atert Bissen | 1 |
| 873 | BATE Borisov | 1 |
| 877 | Ballkani | 1 |
| 843 | Borac Banja Luka | 1 |
| 868 | CSKA Sofia | 2 |
| 887 | Caernarfon Town | 1 |
| 876 | Connah's Quay Nomads | 1 |
| 1288 | Crvena Zvedza | 14 |
| 878 | Differdange 03 | 1 |
| 896 | Dinamo City | 1 |
| 883 | Dinamo Minsk | 1 |
| 886 | Dinamo Tbilisi | 1 |
| 1298 | Dinamo Zagreb | 8 |
| 836 | Drita | 1 |
| 862 | Dynamo Kyiv | 2 |
| 854 | Egnatia | 1 |
| 872 | Elbasani | 1 |
| 880 | Elimai Semey | 1 |
| 894 | FC Santa Coloma | 1 |
| 1316 | FK Kairat | 8 |
| 895 | FK Sarajevo | 1 |
| 867 | Ferencváros | 2 |
| 851 | Flora Tallinn | 1 |
| 840 | Floriana | 1 |
| 848 | Győri ETO | 1 |
| 864 | Hajduk Split | 2 |
| 852 | Iberia 1999 | 1 |
| 832 | Inter Club d'Escaldes | 1 |
| 898 | Jablonec | 1 |
| 849 | Kairat Almaty | 2 |
| 835 | Kauno Žalgiris | 1 |
| 845 | KÍ Klaksvík | 1 |
| 871 | La Fiorita | 1 |
| 842 | Larne | 1 |
| 888 | Levadia Tallinn | 1 |
| 844 | Levski Sofia | 2 |
| 831 | Lincoln Red Imps | 1 |
| 882 | Linfield | 1 |
| 890 | Malisheva | 1 |
| 855 | Maxline Vitebsk | 1 |
| 885 | Mondorf-les-Bains | 1 |
| 891 | NSÍ Runavík | 1 |
| 881 | Nõmme Kalju | 1 |
| 1257 | PAE AEK | 8 |
| 1312 | Paphos FC | 8 |
| 893 | Pen-y-Bont | 1 |
| 853 | Petrocub Hîncești | 1 |
| 858 | Qarabağ | 2 |
| 1308 | Qarabağ Ağdam | 10 |
| 1296 | RB Salzburg | 14 |
| 834 | Riga FC | 2 |
| 837 | Sabah Baku | 3 |
| 1268 | Sabah FK | 8 |
| 1277 | Shaktar | 22 |
| 860 | Sheriff Tiraspol | 2 |
| 884 | Sileks | 1 |
| 1252 | Sl. Bratislava | 16 |
| 1266 | Slavia Praha | 16 |
| 1300 | Sparta Praha | 8 |
| 850 | Sutjeska | 1 |
| 838 | The New Saints | 2 |
| 875 | Torpedo Kutaisi | 1 |
| 869 | Torreense | 1 |
| 841 | Tre Fiori | 1 |
| 870 | UNA Strassen | 1 |
| 1307 | Union SG | 8 |
| 863 | Universitatea Cluj | 2 |
| 856 | Universitatea Craiova | 1 |
| 839 | Vardar | 1 |
| 859 | Vestri | 2 |
| 889 | Vllaznia Shkodër | 1 |
| 866 | Vojvodina | 2 |
| 847 | Víkingur Reykjavík | 1 |
| 874 | Zirə | 1 |
| 892 | Ħamrun Spartans | 1 |
| 865 | Žilina | 2 |

## Ambiguous aliases (one spelling -> several teams; never used to resolve, teamnames.py) (45)

| alias | source | team_ids |
|---|---|---|
| ajax | football_data_org | [346, 1313] |
| arsenal | football_data_org | [3, 1258] |
| aston villa | football_data_org | [14, 1251] |
| atalanta | football_data_org | [137, 1306] |
| athletic | football_data_org | [185, 1272] |
| bologna | football_data_org | [144, 1299] |
| braga | football_data_org | [315, 1293] |
| brest | football_data_org | [276, 1304] |
| chelsea | football_data_org | [17, 1314] |
| como | thesportsdb | [148, 1317] |
| dortmund | football_data_org | [240, 1259] |
| feyenoord | football_data_org | [354, 1264] |
| frankfurt | football_data_org | [244, 1315] |
| inter | football_data_org | [132, 1275] |
| juventus | football_data_org | [141, 1297] |
| lazio | football_data_org | [139, 1286] |
| lens | football_data_org | [277, 1261] |
| leverkusen | football_data_org | [234, 1302] |
| lille | football_data_org | [271, 1281] |
| liverpool | football_data_org | [18, 1274] |
| man city | football_data_org | [2, 1262] |
| man utd | football_data_org | [19, 1271] |
| marseille | football_data_org | [272, 1310] |
| milan | football_data_org | [145, 1283] |
| monaco | football_data_org | [279, 1303] |
| napoli | football_data_org | [129, 1263] |
| newcastle | football_data_org | [13, 1284] |
| paris | thesportsdb | [274, 291] |
| paris sg | football_data_org | [274, 1279] |
| porto | football_data_org | [330, 1265] |
| psv | football_data_org | [342, 1255] |
| rb leipzig | football_data_org | [235, 1260] |
| real betis | football_data_org | [190, 1253] |
| real madrid | football_data_org | [186, 1254] |
| real sociedad | football_data_org | [181, 1294] |
| roma | football_data_org | [134, 1280] |
| sevilla | football_data_org | [179, 1292] |
| sl benfica | football_data_org | [332, 1295] |
| sp cp | football_data_org | [321, 1270] |
| stuttgart | football_data_org | [236, 1276] |
| tottenham | football_data_org | [16, 1309] |
| union berlin | football_data_org | [242, 1290] |
| villarreal | football_data_org | [189, 1267] |
| villarreal | thesportsdb | [189, 1267] |
| vitoria | football_data_org | [326, 685] |
