import pandas as pd 
import cvxpy as cp

def run_levelised_cost_minimisation(
        SOLAR_CAPACITY,
        SOLAR_PPA_DOL_KWH,
        hourly_solar_production_kwh,
        hourly_dayahead_dol_per_kwh,
        ELECTROLYSIS_EFFICIENCY,
        COMPRESSION_EFFICIENCY,
        LIQUEFACTION_EFFICIENCY,
        LIQUEFACTION_MAX_UP,
        LIQUEFACTION_MAX_DOWN,
        OFFTAKE_TPD,
        NUM_DAYS,
        ELECTROLYSIS_CAPEX_DOL_kgPD,
        COMPRESSOR_CAPEX_DOL_kgPD,
        LIQUEFACTION_CAPEX_DOL_kgPD,
        GREEN_THRESHOLD_kg_per_kg,
        ERCTO_CO2_kg_per_kwh,
        T
        ):
    
    realtime_consumption = cp.Variable(T, nonneg = True)
    realtime_supplied = cp.Variable(T, nonneg = True)
    solar_consumed_facility = cp.Variable(T, nonneg = True) 

    #   Design decision variables
    electrolyser_nameplate_capacity_hour = cp.Variable(nonneg = True)
    compressor_nameplate_capacity_hour = cp.Variable(nonneg = True)
    liquefaction_nameplate_capacity_hour = cp.Variable(nonneg = True)

    # set throughput
    electrolyser_throughput = cp.Variable(T, nonneg = True)
    compressor_throughput = cp.Variable(T, nonneg = True)
    compressor_to_liquefaction = cp.Variable(T, nonneg = True)
    liquefacion_throughput = cp.Variable(T, nonneg = True)

    #   Operational decision variables
    gh2_storage_inflow = cp.Variable(T,nonneg=True)
    gh2_storage_outflow = cp.Variable(T,nonneg=True)
    gh2_storage_level = cp.Variable(T+1, nonneg = True)
    lh2_storage_level = cp.Variable(T+1, nonneg = True)
    gh2_storage_active = cp.Variable(T, boolean=True)

    # Define power balance constraints t
    constraints = [
        # restrict the amount of solar that can be consumed
        solar_consumed_facility <= SOLAR_CAPACITY * hourly_solar_production_kwh,
        # power balance equation: sum of electricity in = amount consumed           
        realtime_consumption + solar_consumed_facility == 
            ELECTROLYSIS_EFFICIENCY*electrolyser_throughput + 
            COMPRESSION_EFFICIENCY*compressor_throughput + 
            LIQUEFACTION_EFFICIENCY*liquefacion_throughput, 
    ]

    # add 'green' constraint; restrict amount that can be taken from grid
    constraints += [ 
        sum(realtime_consumption) * ERCTO_CO2_kg_per_kwh <= GREEN_THRESHOLD_kg_per_kg * (OFFTAKE_TPD * NUM_DAYS)
    ]

    # operational constraints of equipment
    constraints += [
        # constraint operational bounds of each piece of equipment: 
        0 <= electrolyser_throughput, 
        electrolyser_throughput <= electrolyser_nameplate_capacity_hour,
        0 <= compressor_throughput, 
        compressor_throughput <= compressor_nameplate_capacity_hour,
        0 <= liquefacion_throughput, 
        liquefacion_throughput <= liquefaction_nameplate_capacity_hour
        ]

    # ramp constraints throughput constraints 
    constraints += [ 
        liquefacion_throughput[1:T] - liquefacion_throughput[0:T-1] <= LIQUEFACTION_MAX_UP*liquefaction_nameplate_capacity_hour,
        liquefacion_throughput[0:T-1] - liquefacion_throughput[1:T] <= LIQUEFACTION_MAX_DOWN*liquefaction_nameplate_capacity_hour,
    ]

    # set initial storage levels to empty
    constraints += [ 
        gh2_storage_level[0] == 0,
    ]

    # balance mass through system
    constraints += [
        electrolyser_throughput == compressor_throughput,
        compressor_throughput == compressor_to_liquefaction + gh2_storage_inflow,
        liquefacion_throughput == compressor_to_liquefaction + gh2_storage_outflow,
        gh2_storage_level[1:T+1] == gh2_storage_level[0:T] + gh2_storage_inflow  - gh2_storage_outflow,
        # big-M constraint to only turn on storage if used 
        # TODO: remove if computational issues arise 
        compressor_throughput - liquefacion_throughput <= 1000 * gh2_storage_active,
        gh2_storage_inflow <= 1000*gh2_storage_active,
        gh2_storage_outflow <= 1000*gh2_storage_active
    ]

    # set 1 tph offtake 
    # constraints += [ 
    #     sum(liquefacion_throughput) == cp.Parameter(value=OFFTAKE_TPD*NUM_DAYS)
    # ]

    # Minimize total cost of supply; min(OPEX + CAPEX)
    # OPEX = electricity, CAPEX = annualised capex
    objective = 0

    # add electricity cost from dayahead market consumption
    objective += realtime_consumption @ hourly_dayahead_dol_per_kwh  

    # add electricity cost from solar ppa consumption
    objective += cp.sum(SOLAR_PPA_DOL_KWH * solar_consumed_facility)

    # add capex costs for electrolyser, compressor and liquefaction
    # multiply 24 to get nameplate capacity in kg per day
    objective += (electrolyser_nameplate_capacity_hour * 24) * ELECTROLYSIS_CAPEX_DOL_kgPD
    objective += (compressor_nameplate_capacity_hour * 24) * COMPRESSOR_CAPEX_DOL_kgPD
    objective += (liquefaction_nameplate_capacity_hour * 24) * LIQUEFACTION_CAPEX_DOL_kgPD


    # Define problem
    objective_min = cp.Minimize(objective)
    problem = cp.Problem(objective_min, constraints)

    # Solve problem
    problem.solve()

    operations_df = pd.DataFrame({
        "hourly_dayahead_dol_per_kwh": hourly_dayahead_dol_per_kwh,
        "realtime_production_kwh":realtime_consumption.value,
        "solar_production_kwh": solar_consumed_facility.value, 
        "electrolyser_consumption_kwh": ELECTROLYSIS_EFFICIENCY*electrolyser_throughput.value, 
        "compressor_consumption_kwh": COMPRESSION_EFFICIENCY*compressor_throughput.value, 
        "liquefaction_consumption_kwh": LIQUEFACTION_EFFICIENCY*liquefacion_throughput.value,
        "electrolyser_produced_kg": electrolyser_throughput.value, 
        "compressor_produced_kg": compressor_throughput.value, 
        "liquefaction_produced_kg": liquefacion_throughput.value,
        "compress_to_liquefaction": compressor_to_liquefaction.value,
        "gh2_storage_level_kg": gh2_storage_level.value[0:T],
        # TODO: if problem size allows, add in big-M constraint 
        "gh2_storage_net_inflow": gh2_storage_inflow.value[0:T] - gh2_storage_outflow.value[0:T],
        "gh2_storge_inflow_kg": gh2_storage_inflow.value[0:T], 
        "gh2_storage_outflow_kg": gh2_storage_outflow.value[0:T],
        # "gh2_storage_netflow": gh2_storage_netflow.value
    })

    facility = {
        "electrolyser_capacity_ph":electrolyser_nameplate_capacity_hour.value,
        "compressor_capacity_ph": compressor_nameplate_capacity_hour.value, 
        "liquefaction_capacity_ph": liquefaction_nameplate_capacity_hour.value, 

    }

    return problem, operations_df, facility


def run_profit_maximisation(
        SOLAR_CAPACITY,
        SOLAR_PPA_DOL_KWH,
        hourly_solar_production_kwh,
        hourly_dayahead_dol_per_kwh,
        ELECTROLYSIS_EFFICIENCY,
        COMPRESSION_EFFICIENCY,
        LIQUEFACTION_EFFICIENCY,
        FUEL_CELL_EFFICIENCY,
        LIQUEFACTION_MAX_UP,
        LIQUEFACTION_MAX_DOWN,
        OFFTAKE_TPD,
        NUM_DAYS,
        ELECTROLYSIS_CAPEX_DOL_kgPD,
        COMPRESSOR_CAPEX_DOL_kgPD,
        LIQUEFACTION_CAPEX_DOL_kgPD,
        FUELCELL_CAPEX_DOL_kgPD,
        H2_SALES_PRICE_DOL_per_kg,
        GREEN_THRESHOLD_kg_per_kg,
        ERCTO_CO2_kg_per_kwh,
        T
        ):
    realtime_consumption = cp.Variable(T, nonneg = True)
    realtime_supplied = cp.Variable(T, nonneg = True)
    solar_consumed_facility = cp.Variable(T, nonneg = True) 

    #   Design decision variables
    electrolyser_nameplate_capacity_hour = cp.Variable(nonneg = True)
    compressor_nameplate_capacity_hour = cp.Variable(nonneg = True)
    liquefaction_nameplate_capacity_hour = cp.Variable(nonneg = True)
    fuelcell_nameplate_capacity_hour = cp.Variable(nonneg= True)

    # set throughput
    electrolyser_throughput = cp.Variable(T, nonneg = True)
    compressor_throughput = cp.Variable(T, nonneg = True)
    compressor_to_liquefaction = cp.Variable(T, nonneg = True)
    liquefacion_throughput = cp.Variable(T, nonneg = True)
    fuel_cell_throughput = cp.Variable(T, nonneg = True)

    #   Operational decision variables
    gh2_storage_inflow = cp.Variable(T,nonneg=True)
    gh2_storage_outflow = cp.Variable(T,nonneg=True)
    gh2_storage_level = cp.Variable(T+1, nonneg = True)
    lh2_storage_level = cp.Variable(T+1, nonneg = True)
    gh2_storage_active = cp.Variable(T, boolean=True)

    # Define power balance constraints t
    constraints = [
        # restrict the amount of solar that can be consumed
        solar_consumed_facility <= SOLAR_CAPACITY * hourly_solar_production_kwh,
        # power balance equation: sum of electricity in = amount consumed           
        realtime_consumption + solar_consumed_facility == 
            ELECTROLYSIS_EFFICIENCY*electrolyser_throughput + 
            COMPRESSION_EFFICIENCY*compressor_throughput + 
            LIQUEFACTION_EFFICIENCY*liquefacion_throughput, 
    ]

    # add 'green' constraint; restrict amount that can be taken from grid
    constraints += [ 
        sum(realtime_consumption) * ERCTO_CO2_kg_per_kwh <= GREEN_THRESHOLD_kg_per_kg * sum(liquefacion_throughput + fuel_cell_throughput)# (OFFTAKE_TPD * NUM_DAYS)
    ]

    # operational constraints of equipment
    constraints += [
        # constraint operational bounds of each piece of equipment: 
        0 <= electrolyser_throughput, 
        electrolyser_throughput <= electrolyser_nameplate_capacity_hour,
        0 <= compressor_throughput, 
        compressor_throughput <= compressor_nameplate_capacity_hour,
        0 <= liquefacion_throughput, 
        liquefacion_throughput <= liquefaction_nameplate_capacity_hour,
        0 <= fuel_cell_throughput, 
        fuel_cell_throughput <= fuelcell_nameplate_capacity_hour,
        # 0.81 <= fuelcell_nameplate_capacity_hour
        ]

    # ramp constraints throughput constraints 
    constraints += [ 
        liquefacion_throughput[1:T] - liquefacion_throughput[0:T-1] <= LIQUEFACTION_MAX_UP*liquefaction_nameplate_capacity_hour,
        liquefacion_throughput[0:T-1] - liquefacion_throughput[1:T] <= LIQUEFACTION_MAX_DOWN*liquefaction_nameplate_capacity_hour,
    ]

    # add fuel cell offtake 
    constraints += [ 
        fuel_cell_throughput*FUEL_CELL_EFFICIENCY == realtime_supplied, 

    ]

    # set initial storage levels to empty
    constraints += [ 
        gh2_storage_level[0] == 0,
    ]

    # balance mass through system
    constraints += [
        electrolyser_throughput == compressor_throughput,
        compressor_throughput == compressor_to_liquefaction + gh2_storage_inflow,
        liquefacion_throughput == compressor_to_liquefaction + gh2_storage_outflow,
        gh2_storage_level[1:T+1] == gh2_storage_level[0:T] + gh2_storage_inflow  - gh2_storage_outflow - fuel_cell_throughput,
        # big-M constraint to only turn on storage if used 
        # TODO: remove if computational issues arise 
        compressor_throughput - liquefacion_throughput <= 1000 * gh2_storage_active,
        gh2_storage_inflow <= 1000*gh2_storage_active,
        gh2_storage_outflow <= 1000*gh2_storage_active
    ]

    # set 1 tph offtake 
    # constraints += [ 
    #     sum(liquefacion_throughput) == cp.Parameter(value=OFFTAKE_TPD*NUM_DAYS)
    # ]

    # Minimize total cost of supply; min(OPEX + CAPEX)
    # OPEX = electricity, CAPEX = annualised capex
    objective = 0

    # add electricity cost from dayahead market consumption
    objective -= realtime_consumption @ hourly_dayahead_dol_per_kwh  

    # add electricity cost from solar ppa consumption
    objective -= cp.sum(SOLAR_PPA_DOL_KWH * solar_consumed_facility)

    objective += realtime_supplied @ hourly_dayahead_dol_per_kwh  
    # H2 SALES REVENUE 
    objective +=   sum(liquefacion_throughput) * H2_SALES_PRICE_DOL_per_kg

    # add capex costs for electrolyser, compressor and liquefaction
    # multiply 24 to get nameplate capacity in kg per day
    objective -= (electrolyser_nameplate_capacity_hour * 24) * ELECTROLYSIS_CAPEX_DOL_kgPD
    objective -= (compressor_nameplate_capacity_hour * 24) * COMPRESSOR_CAPEX_DOL_kgPD
    objective -= (liquefaction_nameplate_capacity_hour * 24) * LIQUEFACTION_CAPEX_DOL_kgPD
    objective -= (fuelcell_nameplate_capacity_hour * 24) * FUELCELL_CAPEX_DOL_kgPD


    # Define problem
    objective_min = cp.Maximize(objective)
    problem = cp.Problem(objective_min, constraints)

    # Solve problem
    problem.solve()

    facility_summary = {
        "electrolyser_capacity_ph":electrolyser_nameplate_capacity_hour.value,
        "compressor_capacity_ph": compressor_nameplate_capacity_hour.value, 
        "liquefaction_capacity_ph": liquefaction_nameplate_capacity_hour.value, 
        "fuelcell_capacity_ph":fuelcell_nameplate_capacity_hour.value,
        "h2_sold": sum(liquefacion_throughput.value), 
        "h2_revenue":  sum(liquefacion_throughput.value) * H2_SALES_PRICE_DOL_per_kg, 
        "solar_consumed": sum(solar_consumed_facility.value), 
        "solar_cost": sum(solar_consumed_facility.value) * SOLAR_PPA_DOL_KWH, 
        "wholesale_consumed": sum(realtime_consumption.value),
        "wholesale_cost": realtime_consumption.value @ hourly_dayahead_dol_per_kwh, 
        "wholesale_supplied": sum(realtime_supplied.value), 
        "wholesale_revenue": realtime_supplied.value @ hourly_dayahead_dol_per_kwh, 
        "total_profit": problem.value, 
        "electrolyser_capex_annualised":(electrolyser_nameplate_capacity_hour.value * 24) * ELECTROLYSIS_CAPEX_DOL_kgPD,
        "compression_capex_annualised":(compressor_nameplate_capacity_hour.value * 24) * COMPRESSOR_CAPEX_DOL_kgPD,
        "liquefaction_capex_annualised":(liquefaction_nameplate_capacity_hour.value * 24) * LIQUEFACTION_CAPEX_DOL_kgPD,
        "fuelcell_capex_annualised":(fuelcell_nameplate_capacity_hour.value * 24) * FUELCELL_CAPEX_DOL_kgPD

    }

    operations_df = pd.DataFrame({"hourly_dayahead_dol_per_kwh": hourly_dayahead_dol_per_kwh,
            "realtime_production_kwh":realtime_consumption.value,
            "realtime_supplied_kwh": realtime_supplied.value,
            "solar_production_kwh": solar_consumed_facility.value, 
            "electrolyser_consumption_kwh": ELECTROLYSIS_EFFICIENCY*electrolyser_throughput.value, 
            "compressor_consumption_kwh": COMPRESSION_EFFICIENCY*compressor_throughput.value, 
            "liquefaction_consumption_kwh": LIQUEFACTION_EFFICIENCY*liquefacion_throughput.value,
            "electrolyser_produced_kg": electrolyser_throughput.value, 
            "compressor_produced_kg": compressor_throughput.value, 
            "liquefaction_produced_kg": liquefacion_throughput.value,
            "compress_to_liquefaction": compressor_to_liquefaction.value,
            "fuel_cell_consumed_kg": fuel_cell_throughput.value,
            "gh2_storage_level_kg": gh2_storage_level.value[0:T],
            # TODO: if problem size allows, add in big-M constraint 
            "gh2_storage_net_inflow": gh2_storage_inflow.value - gh2_storage_outflow.value,
            "gh2_storge_inflow_kg": gh2_storage_inflow.value, 
            "gh2_storage_outflow_kg": gh2_storage_outflow.value
        })

    return problem, operations_df, facility_summary


