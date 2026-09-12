# /compare: verdict matrix, parameters and divergence

Frozen build at 2025-08-29T10:30 (the live page runs the same code at the wall clock). Population model: priors, glucose 120 at steady state, no history.

## Verdict matrix (6 prompts x 3 people)

Rule: on every prompt the three verdicts are three different classes (go ahead / yes, with a condition / better to wait) and the three reasons name three different causes.

| prompt | Alex | Priya | Marcus | ok |
|---|---|---|---|---|
| Can I have a large pepperoni pizza for dinner? | **Go ahead** (insulin_strong: your insulin works better than the average person's) | **Better to wait** (carbs: carbs hit you fast) | **Yes, but less** (sleep: your insulin is working 34% below usual after night shifts) | ok |
| Two slices of cheesecake right now? | **Go ahead** (active_insulin: the 2.0 units for breakfast at 8:03 am are still active) | **Better to wait** (carbs: carbs hit you fast) | **Yes, but less** (sleep: your insulin is working 34% below usual after night shifts) | ok |
| 30 minute run in an hour? | **Yes, with a snack** (exercise_effect: exercise drops your glucose much more than most) | **Better to wait** (liver: your liver stores are only half full, so a dip is harder to catch) | **Go ahead** (sleep: your insulin is working 34% below usual after night shifts) | ok |
| Large latte with a muffin now? | **Go ahead** (caffeine: there is still about 293 mg of caffeine in you) | **Better to wait** (carbs: carbs hit you fast) | **Yes, but less** (sleep: your insulin is working 34% below usual after night shifts) | ok |
| Three glasses of wine at 9 pm tonight? | **Yes, with a snack** (insulin_strong: your insulin works better than the average person's) | **Better to wait** (alcohol: alcohol lowers you much more than most) | **Go ahead** (sleep: your insulin is working 34% below usual after night shifts) | ok |
| Big bowl of pasta at 9 pm? | **Yes, but less** (insulin_strong: your insulin works better than the average person's) | **Better to wait** (carbs: carbs hit you fast) | **Go ahead** (sleep: your insulin is working 34% below usual after night shifts) | ok |

## Fitted parameters (after tuning, if any)

| parameter | Alex | Priya | Marcus | prior |
|---|---|---|---|---|
| carb bioavailability (`carb_ratio`) | 0.905 | 0.800 * | 0.673 | 0.800 |
| absorption time constant (min) (`tau_carb`) | 37.328 | 24.497 | 46.669 | 40.000 |
| insulin sensitivity, night (`si_tod0`) | 0.950 | 0.550 * | 0.878 | 0.850 |
| insulin sensitivity, day (`si_tod1`) | 1.168 | 0.699 | 0.923 | 1.000 |
| insulin sensitivity, evening (`si_tod2`) | 1.100 | 0.700 * | 1.109 | 1.100 |
| sleep-debt effect (`sleep_debt_coef`) | 0.435 | 0.200 | 0.270 * | 0.200 |
| exercise effect (`exercise_mult`) | 1.700 * | 0.302 | 0.800 * | 1.000 |

`*` = tuned for the demo (backend/data/compare_personas.json), within the plausible ranges.

## Starting point

| | Alex | Priya | Marcus |
|---|---|---|---|
| glucose now | 144 | 197 | 201 |
| trend | steady | steady | steady |
| time in range, 7 d (%) | 66 | 63 | 65 |
| average, 7 d | 153 | 153 | 157 |
| lows, 7 d (episodes of 15+ min) | 5 | 6 | 2 |
| carb ratio | 1 unit covers 27 g | 1 unit covers 25 g | 1 unit covers 37 g |
| insulin working (%) | 96 | 106 | 66 |
| recovery | 97 | 74 | 57 |
| amber / red tiles | caffeine, liver | energy, liver | caffeine, energy, recovery, insulin, liver |
| next meal | 2025-08-29T12:30 | 2025-08-29T13:00 | 2025-08-29T12:15 |
| learned chips | 💉 basal runs weak ↑; 💉 insulin best daytime; 🍞 carbs count more ↑ | 🍞 carbs hit fast ↑; 💉 insulin weak evenings ↓; 💉 insulin weak overnight ↓ | 😴 insulin down after shifts ↓; 💉 basal runs weak ↑; 🍞 carbs hit slow ↓ |

## The six prompts in detail

| prompt | person | verdict | cause | peak | at | low | P(low) | condition |
|---|---|---|---|---|---|---|---|---|
| Can I have a large pepperoni pizza for dinner? | Alex | Go ahead | insulin_strong | 213 | 8:05 pm | 159 | unlikely (0.01) | - |
| Can I have a large pepperoni pizza for dinner? | Priya | Better to wait | carbs | 283 | 8:15 pm | 106 | likely (0.20) | - |
| Can I have a large pepperoni pizza for dinner? | Marcus | Yes, but less | sleep | 255 | 10:55 pm | 191 | unlikely (0.00) | Have half as much |
| Can I have a large pepperoni pizza for dinner? | average person | Better to wait | - | 143 | 8:05 pm | 104 | possible (0.17) | - |
| | *divergence* | 3 classes | 3 causes | spread 70 | spread 170 min | | | **ok** |
| Two slices of cheesecake right now? | Alex | Go ahead | active_insulin | 177 | 11:30 am | 143 | unlikely (0.04) | - |
| Two slices of cheesecake right now? | Priya | Better to wait | carbs | 299 | 11:35 am | 196 | unlikely (0.01) | - |
| Two slices of cheesecake right now? | Marcus | Yes, but less | sleep | 278 | 2:30 pm | 200 | unlikely (0.00) | Have half as much |
| Two slices of cheesecake right now? | average person | Go ahead | - | 161 | 11:45 am | 119 | unlikely (0.03) | - |
| | *divergence* | 3 classes | 3 causes | spread 122 | spread 180 min | | | **ok** |
| 30 minute run in an hour? | Alex | Yes, with a snack | exercise_effect | 144 | 10:30 am | 78 | possible (0.11) | Eat a small snack (about 20 g of carbs) 15 minutes before |
| 30 minute run in an hour? | Priya | Better to wait | liver | 327 | 2:05 pm | 62 | likely (0.00) | - |
| 30 minute run in an hour? | Marcus | Go ahead | sleep | 215 | 2:00 pm | 171 | unlikely (0.00) | - |
| 30 minute run in an hour? | average person | Go ahead | - | 121 | 11:00 am | 81 | unlikely (0.00) | - |
| | *divergence* | 3 classes | 3 causes | spread 183 | spread 215 min | | | **ok** |
| Large latte with a muffin now? | Alex | Go ahead | caffeine | 206 | 11:40 am | 144 | unlikely (0.01) | - |
| Large latte with a muffin now? | Priya | Better to wait | carbs | 328 | 2:00 pm | 197 | unlikely (0.00) | - |
| Large latte with a muffin now? | Marcus | Yes, but less | sleep | 302 | 1:30 pm | 201 | unlikely (0.00) | Have half as much |
| Large latte with a muffin now? | average person | Go ahead | - | 200 | 11:55 am | 119 | unlikely (0.00) | - |
| | *divergence* | 3 classes | 3 causes | spread 122 | spread 140 min | | | **ok** |
| Three glasses of wine at 9 pm tonight? | Alex | Yes, with a snack | insulin_strong | 217 | 8:00 pm | 78 | possible (0.16) | Eat 15 g of carbs before bed (no insulin for it) |
| Three glasses of wine at 9 pm tonight? | Priya | Better to wait | alcohol | 274 | 8:00 pm | 46 | likely (0.91) | - |
| Three glasses of wine at 9 pm tonight? | Marcus | Go ahead | sleep | 223 | 8:50 pm | 72 | likely (0.49) | - |
| Three glasses of wine at 9 pm tonight? | average person | Yes, but less | - | 108 | 8:00 pm | 76 | likely (0.24) | Have half as much |
| | *divergence* | 3 classes | 3 causes | spread 57 | spread 50 min | | | **ok** |
| Big bowl of pasta at 9 pm? | Alex | Yes, but less | insulin_strong | 216 | 10:00 pm | 78 | unlikely (0.04) | Have half as much |
| Big bowl of pasta at 9 pm? | Priya | Better to wait | carbs | 274 | 8:00 pm | 88 | likely (0.27) | - |
| Big bowl of pasta at 9 pm? | Marcus | Go ahead | sleep | 237 | 10:05 pm | 202 | unlikely (0.01) | - |
| Big bowl of pasta at 9 pm? | average person | Better to wait | - | 150 | 10:15 pm | 105 | possible (0.14) | - |
| | *divergence* | 3 classes | 3 causes | spread 58 | spread 125 min | | | **ok** |
