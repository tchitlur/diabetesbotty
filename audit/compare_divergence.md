# /compare: parameters and divergence

Frozen at 2025-08-29T10:30 (Friday). Population model: priors, glucose 120 at steady state, no history.

## Fitted parameters (after tuning, if any)

| parameter | Alex | Priya | Marcus | prior |
|---|---|---|---|---|
| carb bioavailability (`carb_ratio`) | 0.643 | 0.749 | 0.720 * | 0.800 |
| absorption time constant (min) (`tau_carb`) | 35.436 | 22.000 * | 48.000 * | 40.000 |
| insulin sensitivity, night (`si_tod0`) | 1.250 | 0.550 * | 0.800 * | 0.850 |
| insulin sensitivity, day (`si_tod1`) | 1.026 | 0.560 * | 0.900 * | 1.000 |
| insulin sensitivity, evening (`si_tod2`) | 1.149 | 0.640 * | 1.150 * | 1.100 |
| sleep-debt effect (`sleep_debt_coef`) | 0.129 | 0.276 | 0.380 * | 0.200 |
| exercise effect (`exercise_mult`) | 0.797 | 0.545 | 1.124 | 1.000 |

`*` = tuned for the demo (backend/data/compare_personas.json), within the plausible ranges.

## Starting point

| | Alex | Priya | Marcus |
|---|---|---|---|
| glucose now | 112 | 107 | 182 |
| time in range, 7 d (%) | 72 | 67 | 79 |
| average, 7 d | 100 | 127 | 103 |
| lows, 7 d | 21 | 10 | 17 |
| carb ratio | 1 unit covers 37 g | 1 unit covers 17 g | 1 unit covers 25 g |
| insulin working (%) | 102 | 80 | 78 |
| recovery | 93 | 79 | 86 |

## The six prompts

| prompt | person | verdict | peak | at | low | P(low) | condition |
|---|---|---|---|---|---|---|---|
| Can I have a large pepperoni pizza for dinner? | Alex | Better to wait | 182 | 8:20 pm | 132 | possible (0.12) | - |
| Can I have a large pepperoni pizza for dinner? | Priya | Better to wait | 276 | 8:15 pm | 87 | likely (0.37) | - |
| Can I have a large pepperoni pizza for dinner? | Marcus | Yes, but less | 181 | 7:55 pm | 128 | possible (0.05) | Have half as much |
| Can I have a large pepperoni pizza for dinner? | average person | Better to wait | 138 | 8:10 pm | 101 | possible (0.19) | - |
| | *divergence* | differ | spread 95 | spread 25 min | | | **ok** (2/3) |
| Two slices of cheesecake right now? | Alex | Yes, but less | 147 | 11:40 am | 112 | possible (0.07) | Have half as much |
| Two slices of cheesecake right now? | Priya | Better to wait | 219 | 11:45 am | 105 | possible (0.14) | - |
| Two slices of cheesecake right now? | Marcus | Yes, but less | 225 | 3:00 pm | 182 | unlikely (0.00) | Have half as much |
| Two slices of cheesecake right now? | average person | Go ahead | 161 | 11:45 am | 119 | unlikely (0.04) | - |
| | *divergence* | differ | spread 78 | spread 200 min | | | **ok** (3/3) |
| 30 minute run at 7 am tomorrow? | Alex | Yes, with a snack | 72 | 6:00 am | 47 | very likely (1.00) | Have 15 g of fast carbs first |
| 30 minute run at 7 am tomorrow? | Priya | Yes, with a snack | 143 | 7:00 am | 107 | likely (0.20) | Eat a small snack (about 20 g of carbs) 15 minutes before |
| 30 minute run at 7 am tomorrow? | Marcus | Yes, with a snack | 192 | 6:00 am | 71 | likely (0.47) | Have 15 g of fast carbs first |
| 30 minute run at 7 am tomorrow? | average person | Yes, with a snack | 107 | 7:00 am | 59 | very likely (1.00) | Have 15 g of fast carbs first |
| | *divergence* | same | spread 120 | spread 60 min | | | **ok** (2/3) |
| Large latte with a muffin now? | Alex | Go ahead | 169 | 11:50 am | 112 | unlikely (0.01) | - |
| Large latte with a muffin now? | Priya | Better to wait | 237 | 11:35 am | 106 | possible (0.08) | - |
| Large latte with a muffin now? | Marcus | Yes, but less | 251 | 12:10 pm | 182 | unlikely (0.00) | Have half as much |
| Large latte with a muffin now? | average person | Go ahead | 200 | 11:50 am | 119 | unlikely (0.00) | - |
| | *divergence* | differ | spread 82 | spread 35 min | | | **ok** (3/3) |
| Skip lunch today? | Alex | Go ahead | 130 | 6:30 pm | 95 | unlikely (0.02) | - |
| Skip lunch today? | Priya | Yes, with a snack | 106 | 10:30 am | 76 | likely (0.23) | Have 15 g of carbs around 1:15 pm |
| Skip lunch today? | Marcus | Go ahead | 186 | 12:25 pm | 171 | unlikely (0.00) | - |
| Skip lunch today? | average person | Go ahead | 122 | 11:00 am | 108 | unlikely (0.00) | - |
| | *divergence* | differ | spread 80 | spread 480 min | | | **ok** (3/3) |
| Big bowl of pasta at 9 pm? | Alex | Yes, with one change | 189 | 10:20 pm | 128 | possible (0.12) | This adds no risk, but you are already trending low : treat the low first (15 g fast carbs) and re-check in 20 min |
| Big bowl of pasta at 9 pm? | Priya | Better to wait | 283 | 10:10 pm | 90 | likely (0.28) | - |
| Big bowl of pasta at 9 pm? | Marcus | Go ahead | 188 | 10:00 pm | 140 | unlikely (0.03) | - |
| Big bowl of pasta at 9 pm? | average person | Better to wait | 144 | 10:20 pm | 99 | possible (0.17) | - |
| | *divergence* | differ | spread 95 | spread 20 min | | | **ok** (2/3) |
