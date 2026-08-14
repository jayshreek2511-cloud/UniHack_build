import pandas as pd

rows = [
    # 5 New Dishwashers
    {"PART_NUMBER": 9001, "Part_Desc": "SHPM65Z55N Bosch 500 Series 24 Inch Built-In Dishwasher 44 dBA 120V 12A Stainless Steel", "E1_Brand": "Bosch", "Unilog_Brand": "Bosch", "DIB_Brand": "Bosch", "Part_Manuf": "Bosch Home Appliances"},
    {"PART_NUMBER": 9002, "Part_Desc": "DW80R9950US Samsung Linear Wash 24 in Top Control Built In Dishwasher 39 dBA 120V 15A Stainless Steel", "E1_Brand": "Samsung", "Unilog_Brand": "Samsung", "DIB_Brand": "Samsung", "Part_Manuf": "Samsung Electronics"},
    {"PART_NUMBER": 9003, "Part_Desc": "GDT695SSJSS GE 24 Inch Built In Dishwasher 48 dBA 120V 15A Stainless Steel", "E1_Brand": "GE Appliances", "Unilog_Brand": "GE Appliances", "DIB_Brand": "GE", "Part_Manuf": "GE Appliances"},
    {"PART_NUMBER": 9004, "Part_Desc": "G7316SCU Miele 24 Inch Built In Dishwasher AutoDos 42 dBA 120V 15A Clean Touch Steel", "E1_Brand": "Miele", "Unilog_Brand": "Miele", "DIB_Brand": "Miele", "Part_Manuf": "Miele Inc"},
    {"PART_NUMBER": 9005, "Part_Desc": "LDFN4542D LG Front Control Dishwasher QuadWash 50 dBA 120V 15A Black Stainless Steel", "E1_Brand": "LG", "Unilog_Brand": "LG", "DIB_Brand": "LG", "Part_Manuf": "LG Electronics"},
    # 3 Non-Dishwasher rows
    {"PART_NUMBER": 9006, "Part_Desc": "Heavy Duty Industrial Circuit Breaker 20A 120V Single Pole", "E1_Brand": "Square D", "Unilog_Brand": "Square D", "DIB_Brand": "Square D", "Part_Manuf": "Schneider Electric"},
    {"PART_NUMBER": 9007, "Part_Desc": "Stainless Steel Hex Bolt 3/8-16 x 1-1/2 in Grade 316", "E1_Brand": "Fastenal", "Unilog_Brand": "Fastenal", "DIB_Brand": "Fastenal", "Part_Manuf": "Fastenal Company"},
    {"PART_NUMBER": 9008, "Part_Desc": "Flexible PVC Conduit Tubing 1/2 in 100 ft Roll", "E1_Brand": "Carlon", "Unilog_Brand": "Carlon", "DIB_Brand": "Carlon", "Part_Manuf": "Carlon Industries"},
]

df = pd.DataFrame(rows)
df.to_csv("data/input/test_5_new_dishwashers.csv", index=False)
print("Created data/input/test_5_new_dishwashers.csv with 8 rows (5 dishwashers + 3 non-dishwashers)")
