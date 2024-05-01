This folder contains the following: 

1. 'data' folder 
'data/2019_ercot_day_ahead_price.csv' - .csv file storing dayahead prices for ERCOT market 2019
'data/2019_ercot_real_time_price' - .csv file storing realtime prices for ERCOT market 2019
'data/data_notebook.ipynb' - notebook used to create power .csv required for optimisation
'data/solar_profile_29_-95.csv' - file storing solar production profile from renewables ninja

2. 'annual_profit_optimisation.py' - python file storing function for annual profit optimisation

3. 'optimisation_notebook_annual_profit_optimisation.ipynb' - Jupyter notebook to produce results / analysis  using 'annual_profit_optimisation.py' to run the annual profit optimisation (stage 1)

4. 'optimisation_rolling_horizon_v2.ipynb' - Jupyter notebook to produce results / analysis  using 'rolling_horizon_optimisation.py' to run the rolling horion optimisation (stage 2)

5. 'rolling_horizon_optimisation.py' - python file storing function for calculating the rolling horizon optimisation. 