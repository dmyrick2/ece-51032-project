import pandas as pd 
import cvxpy as cp

def run_rolling_horizon_opt(
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
        electrolyser_nameplate_capacity_hour,
        compressor_nameplate_capacity_hour,
        liquefaction_nameplate_capacity_hour,
        fuelcell_nameplate_capacity_hour,
        H2_SALES_PRICE_DOL_per_kg,
        GREEN_THRESHOLD_kg_per_kg,
        ERCTO_CO2_kg_per_kwh,
        T,
        prev_state_vector):
    realtime_consumption = cp.Variable(T, nonneg = True)
    realtime_supplied = cp.Variable(T, nonneg = True)
    solar_consumed_facility = cp.Variable(T, nonneg = True) 

    # set throughput
    electrolyser_throughput = cp.Variable(T, nonneg = True)
    compressor_throughput = cp.Variable(T, nonneg = True)
    compressor_to_liquefaction = cp.Variable(T, nonneg = True)
    liquefacion_throughput = cp.Variable(T, nonneg = True)
    liquefaction_on_off = cp.Variable(T, boolean=True)
    liquefaction_state_change = cp.Variable(T, integer=True)
    liquefaction_state_change_up = cp.Variable(T, boolean=True)
    liquefaction_state_change_down = cp.Variable(T, boolean=True)
    fuel_cell_throughput = cp.Variable(T, nonneg = True)

    #   Operational decision variables
    gh2_storage_inflow = cp.Variable(T,nonneg=True)
    gh2_storage_outflow = cp.Variable(T,nonneg=True)
    gh2_storage_level = cp.Variable(T+1, nonneg = True)
    lh2_storage_level = cp.Variable(T+1, nonneg = True)
    gh2_storage_active = cp.Variable(T, boolean=True)

    ci_slack = cp.Variable(nonneg=True)

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
        (sum(realtime_consumption) + prev_state_vector['grid_running_sum']) * ERCTO_CO2_kg_per_kwh <=\
              GREEN_THRESHOLD_kg_per_kg * (sum(liquefacion_throughput + fuel_cell_throughput) + prev_state_vector['h2_offtake_running_sum']) + ERCTO_CO2_kg_per_kwh * ci_slack
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
        fuel_cell_throughput <= fuelcell_nameplate_capacity_hour
        ]
    # print(f"**** Max ramp up {LIQUEFACTION_MAX_UP*liquefaction_nameplate_capacity_hour}")
    # print(f"**** Max ramp down {LIQUEFACTION_MAX_DOWN*liquefaction_nameplate_capacity_hour}")
    # ramp constraints throughput constraints 
    LIQ_MIN_OP = 0.3#LIQUEFACTION_MAX_UP
    constraints += [ 
        liquefacion_throughput[1:T] - liquefacion_throughput[0:T-1] <= LIQ_MIN_OP*liquefaction_nameplate_capacity_hour * liquefaction_state_change_up[1:T] + LIQUEFACTION_MAX_UP*liquefaction_nameplate_capacity_hour * (liquefaction_on_off[1:T] - liquefaction_state_change_up[1:T]),
        LIQ_MIN_OP*liquefaction_nameplate_capacity_hour * liquefaction_state_change_up[1:T] <= liquefacion_throughput[1:T] - liquefacion_throughput[0:T-1],
        liquefacion_throughput[0:T-1] - liquefacion_throughput[1:T] <= LIQUEFACTION_MAX_DOWN*liquefaction_nameplate_capacity_hour, 
        liquefacion_throughput <= 1000*liquefaction_on_off,
        liquefaction_on_off <= 1000* liquefacion_throughput,
        liquefaction_state_change >= -1,
        liquefaction_state_change <= 1,
        liquefaction_on_off[1:T] - liquefaction_on_off[0:T-1] == liquefaction_state_change[1:T],
        liquefaction_state_change <= liquefaction_state_change_up,
        liquefaction_state_change >= 2*liquefaction_state_change_up - 1,
        (-1)*liquefaction_state_change <= liquefaction_state_change_down, 
        (-1)*liquefaction_state_change  >= 2*liquefaction_state_change_down - 1
    ]

    # add fuel cell offtake 
    constraints += [ 
        fuel_cell_throughput*FUEL_CELL_EFFICIENCY == realtime_supplied, 

    ]

    print(f"previous liquefaction {prev_state_vector['liquefaction_produced_kg']}")
    # set initial storage levels to empty
    constraints += [ 
        gh2_storage_level[1] == prev_state_vector['gh2_storage_level_kg'],
        liquefacion_throughput[0] == prev_state_vector['liquefaction_produced_kg']
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
    
    objective -= 100 * ci_slack



    # Define problem
    objective_min = cp.Maximize(objective)
    problem = cp.Problem(objective_min, constraints)

    # Solve problem
    problem.solve()

    facility_summary = {
        "electrolyser_capacity_ph":electrolyser_nameplate_capacity_hour,
        "compressor_capacity_ph": compressor_nameplate_capacity_hour, 
        "liquefaction_capacity_ph": liquefaction_nameplate_capacity_hour, 
        "fuelcell_capacity_ph":fuelcell_nameplate_capacity_hour,
        "h2_sold": sum(liquefacion_throughput.value), 
        "h2_revenue":  sum(liquefacion_throughput.value) * H2_SALES_PRICE_DOL_per_kg, 
        "solar_consumed": sum(solar_consumed_facility.value), 
        "solar_cost": sum(solar_consumed_facility.value) * SOLAR_PPA_DOL_KWH, 
        "wholesale_consumed": sum(realtime_consumption.value),
        "wholesale_cost": realtime_consumption.value @ hourly_dayahead_dol_per_kwh, 
        "wholesale_supplied": sum(realtime_supplied.value), 
        "wholesale_revenue": realtime_supplied.value @ hourly_dayahead_dol_per_kwh, 
        "total_profit": problem.value
    }

    operations_df = pd.DataFrame({"hourly_dayahead_dol_per_kwh": hourly_dayahead_dol_per_kwh,
            "realtime_production_kwh":realtime_consumption.value,
            "realtime_supplied_kwh": realtime_supplied.value,
            "solar_available_kwh":SOLAR_CAPACITY*hourly_solar_production_kwh,
            "solar_production_kwh": solar_consumed_facility.value, 
            "grid_running_sum": prev_state_vector['grid_running_sum'],
            "h2_offtake_running_sum": prev_state_vector['h2_offtake_running_sum'],
            "electrolyser_consumption_kwh": ELECTROLYSIS_EFFICIENCY*electrolyser_throughput.value, 
            "compressor_consumption_kwh": COMPRESSION_EFFICIENCY*compressor_throughput.value, 
            "liquefaction_consumption_kwh": LIQUEFACTION_EFFICIENCY*liquefacion_throughput.value,
            "electrolyser_produced_kg": electrolyser_throughput.value, 
            "compressor_produced_kg": compressor_throughput.value,
            "liquefaction_produced_kg": liquefacion_throughput.value,
            "liquefaction_operating": liquefaction_on_off.value,#[1],
            "liquefaction_state_change": liquefaction_state_change.value,
            "liquefaction_state_chang_up": liquefaction_state_change_up.value,
            "compress_to_liquefaction": compressor_to_liquefaction.value,
            "fuel_cell_consumed_kg": fuel_cell_throughput.value,
            "gh2_storage_level_kg": gh2_storage_level.value[0:T],
            # TODO: if problem size allows, add in big-M constraint 
            "gh2_storage_net_inflow": gh2_storage_inflow.value - gh2_storage_outflow.value,
            "gh2_storge_inflow_kg": gh2_storage_inflow.value,
            "gh2_storage_outflow_kg": gh2_storage_outflow.value, 
            "ci_slack": ci_slack.value
        })
    
    operations_t_vector = {
            "grid_running_sum":  prev_state_vector['grid_running_sum'] + realtime_consumption.value[1],
            "h2_offtake_running_sum": prev_state_vector['h2_offtake_running_sum'] + liquefacion_throughput.value[1],
            "hourly_dayahead_dol_per_kwh": hourly_dayahead_dol_per_kwh.tolist()[1],
            "realtime_production_kwh":realtime_consumption.value[1],
            "realtime_supplied_kwh": realtime_supplied.value[1],
            "solar_available_kwh":SOLAR_CAPACITY*hourly_solar_production_kwh.tolist()[1],
            "solar_production_kwh": solar_consumed_facility.value[1], 
            "electrolyser_consumption_kwh": ELECTROLYSIS_EFFICIENCY*electrolyser_throughput.value[1], 
            "compressor_consumption_kwh": COMPRESSION_EFFICIENCY*compressor_throughput.value[1], 
            "liquefaction_consumption_kwh": LIQUEFACTION_EFFICIENCY*liquefacion_throughput.value[1],
            "electrolyser_produced_kg": electrolyser_throughput.value[1], 
            "compressor_produced_kg": compressor_throughput.value[1], 
            "liquefaction_produced_kg": liquefacion_throughput.value[1],
            "liquefaction_operating": liquefaction_on_off.value[1],
            "liquefaction_state_change": liquefaction_state_change[1].value,
            "liquefaction_state_change_up":liquefaction_state_change_up[1].value,
            "liquefaction_state_change_down":liquefaction_state_change_down[1].value,
            "liquefaction_minimum_production":LIQ_MIN_OP*liquefaction_nameplate_capacity_hour,
            "compress_to_liquefaction": compressor_to_liquefaction.value[1],
            "fuel_cell_consumed_kg": fuel_cell_throughput.value[1],
            "gh2_storage_level_kg": gh2_storage_level.value[2],
            # TODO: if problem size allows, add in big-M constraint 
            "gh2_storage_net_inflow": gh2_storage_inflow.value[1] - gh2_storage_outflow.value[1],
            "gh2_storge_inflow_kg": gh2_storage_inflow.value[1], 
            "gh2_storage_outflow_kg": gh2_storage_outflow.value[1],
            "ci_slack": ci_slack.value
        }



    return problem, operations_df, facility_summary, operations_t_vector