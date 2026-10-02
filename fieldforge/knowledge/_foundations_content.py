"""Original FieldForge lessons and fictional exercises, not copied source chapters.

No medical doses, hazardous construction, repairs or food-safety procedures.
Related NIST references support only the identified unit conventions, not review
or endorsement of these original lessons. Content has no independent expert review.
"""

from fieldforge.knowledge._learning_model import Exercise, Lesson


def lessons() -> tuple[Lesson, ...]:
    return (
        Lesson("counting-units", "Count things and name the unit", "foundations: numbers", (),
               "Create a count another learner can reproduce, without confusing packages and contents.", """
START WITH THE QUESTION
A useful number answers a specific question. 'We have 12' is not enough: twelve boxes, twelve sheets, or twelve complete sets? Write the object, the counting unit and the time of the count together. A package count can be exact while its contents are unknown. An empty box and a full box are each one box, but they do not contain the same usable stock.

Choose one uncomplicated practice item, such as blank paper. Separate counted from uncounted material physically while working. Mark groups of five with tally marks, then add complete groups and remaining marks. Recount using a different grouping, such as groups of ten. Two matching counts are useful evidence, but they do not prove that both counts used the correct definition of an item.

PACKAGES ARE A SECOND LEVEL
To turn packages into item counts, you need items per package. Multiplication combines equal groups: number of packages multiplied by items per package. If packages differ, record each type separately and add their item totals. Do not multiply the combined package count by whichever package size is convenient.

WORKED EXAMPLE
A classroom shelf has 4 sealed bundles with 25 blank cards per bundle, plus 13 loose cards. The total is 4 bundles × 25 cards/bundle + 13 cards = 113 cards. If 8 cards are damaged and excluded from the classroom activity, the usable count is 113 − 8 = 105 cards. The count of bundles is still 4; the usable count is a different quantity.

Write the cancellation of 'bundle' in the multiplication. That leaves cards, which can be added to loose cards. Cards cannot be added directly to bundles without a conversion.

CHECK AND RECORD
Use columns for item description, counting unit, package quantity, contents per package, loose items, exclusions, usable total and counted date. Mark an unknown package size as unknown, not zero. A zero is a known absence; unknown means the information has not been established. Retain the original count if you later correct it, explaining the correction in your own record.

TRY IT WITH PAPER
Make two pretend packages with different counts. Exchange a count sheet with another learner and ask them to reproduce your total. Ask what information is missing before permitting any guess. This is a counting exercise, not a determination that real supplies are safe to use.
""", (
            Exercise("Five bundles contain 12 cards each, plus 7 loose cards. How many cards?", "67", "cards",
                     "5 × 12 + 7 = 60 + 7 = 67 cards. Bundles cancel against cards per bundle."),
            Exercise("A count finds 84 cards. Nine are set aside for this activity. How many remain available?", "75", "cards",
                     "84 − 9 = 75 cards; exclusions must not also be counted as available."),
        ), ("inventory", "measurement")),
        Lesson("checking-arithmetic", "Arithmetic you can check twice", "foundations: numbers", ("counting-units",),
               "Use place value, operation order and a second calculation to catch arithmetic mistakes.", """
PLACE VALUE BEFORE SPEED
Each move one place to the left in a base-ten whole number multiplies that place's value by ten. In 304, the 3 means three hundreds, the 0 means no tens, and the 4 means four ones. A written zero keeps the positions clear. In decimal notation, the first place to the right of the point is tenths, then hundredths and thousandths. Align decimal points, not the final digit, when adding measured values.

Break a calculation into smaller named parts. Addition joins amounts measured in the same unit. Subtraction finds a remainder or difference. Multiplication combines equal groups. Division can mean splitting a total into equal groups or asking how many groups of a known size fit. The context determines the unit of the answer.

ORDER AND BRACKETS
Do bracketed work first, then multiplication and division, then addition and subtraction. Within multiplication/division or addition/subtraction, work left to right. Brackets are a useful way to make your intended grouping explicit for another reader. The expressions 18 + 6 × 4 and (18 + 6) × 4 describe different calculations: 42 and 96 respectively.

WORKED EXAMPLE
An exercise starts with 7 packs of 24 counters and removes 19 counters. First calculate 7 × 24 = 7 × (20 + 4) = 140 + 28 = 168. Then subtract 19 to get 149 counters. Check backwards: 149 + 19 = 168. Check multiplication independently: 24 + 24 + 24 + 24 + 24 + 24 + 24 = 168.

Estimate before calculating. Seven packs of roughly 25 counters suggest roughly 175 before removal, so a final answer near 150 is plausible. An answer of 1,490 would fail this scale check. A plausible answer is not necessarily correct; estimation catches gross errors, not every error.

REMAINDERS HAVE MEANING
Dividing 53 counters among groups of 8 produces 6 complete groups with 5 left over, because 6 × 8 + 5 = 53. If you are counting complete groups, the answer is not 6.625 complete groups. If you are describing an average allocation, a fraction might be meaningful. State which question you answered.

PRACTICE HABIT
Keep the original numbers visible, write units beside intermediate results, and check using a different method. If two methods disagree, locate the first differing step rather than choosing the more attractive answer. For practical decisions, arithmetic checking supplements verification of the inputs; it never establishes the safety of a real procedure.
""", (
            Exercise("Calculate 18 + 6 × 4, using multiplication before addition.", "42", "counters",
                     "6 × 4 = 24, then 18 + 24 = 42. Bracketing (18 + 6) first would answer another question."),
            Exercise("There are 53 counters. After making 6 groups of 8, how many counters are left?", "5", "counters",
                     "53 − (6 × 8) = 53 − 48 = 5. Check: 48 + 5 = 53."),
        ), ("measurement", "inventory")),
        Lesson("fractions-decimals", "Fractions, decimals and equal parts", "foundations: numbers", ("checking-arithmetic",),
               "Represent the same portion as a fraction or decimal and add portions with a common denominator.", """
WHAT A FRACTION SAYS
The fraction 3/4 means three parts when the whole is divided into four equal parts. The denominator names the size of the parts; the numerator counts them. State the whole: three quarters of a sheet is not the same area as three quarters of a larger sheet. This lesson uses equal paper strips, not medicines or chemical mixtures.

Multiplying the numerator and denominator by the same nonzero number changes the names of the parts without changing the amount. Thus 1/2 = 2/4 = 4/8. Dividing both by a common factor simplifies a fraction. For 6/8, divide both by 2 to get 3/4. A zero denominator is undefined: there is no equal-part interpretation for dividing a whole into zero parts.

ADDING AND SUBTRACTING
To add fractions, express them in pieces of equal size first. For 1/2 + 1/3, use sixths: 3/6 + 2/6 = 5/6. Adding denominators to get 2/5 does not combine the original portions correctly. Subtraction follows the same rule. Multiplication is different: multiply numerators and denominators, then simplify. Half of three quarters is (1/2) × (3/4) = 3/8.

WORKED EXAMPLE
A paper strip is 1 whole unit long. An activity uses 3/8 of it, then another 1/4. Rewrite 1/4 as 2/8. The used portion is 3/8 + 2/8 = 5/8. The remainder is 8/8 − 5/8 = 3/8. A quick check joins used and remaining pieces: 5/8 + 3/8 = 1.

DECIMAL CONNECTION
A decimal is another fraction notation. The number 0.75 is 75/100, which simplifies to 3/4. The fraction 1/8 equals 0.125. Some fractions do not terminate as decimals: 1/3 = 0.333… . An exact fraction and a rounded decimal are not identical. When this pack's practice checker requests an exact value, enter 1/3 rather than a finite string of threes.

COMPARING AMOUNTS
Use a common denominator, convert exactly where possible, or compare by cross multiplication. To compare 3/5 and 5/8, compare 3 × 8 = 24 with 5 × 5 = 25. Since 24 is smaller, 3/5 is smaller. Both denominators are positive in this example.

TEACH-BACK
Draw equal-length bars to show halves, quarters and eighths. Explain why unequal pieces cannot each be called one eighth. Keep your drawing alongside the arithmetic so a learner can check both the picture and the symbols.
""", (
            Exercise("What fraction of one strip remains after using 3/8 and then 1/4?", "3/8", "of the strip",
                     "1/4 = 2/8. Used = 5/8, so remaining = 8/8 − 5/8 = 3/8, also 0.375."),
            Exercise("Write 0.625 as an exact fraction or equivalent decimal.", "5/8", "of one whole",
                     "0.625 = 625/1000 = 5/8. Either exact representation describes the same number."),
        ), ("measurement",)),
        Lesson("ratios-scaling", "Ratios and proportional batches", "foundations: numbers", ("fractions-decimals",),
               "Scale a harmless paper activity while keeping the difference between part-to-part and part-to-whole ratios.", """
TWO DIFFERENT COMPARISONS
A ratio compares quantities. In a paper pattern containing 2 blue squares for every 3 white squares, blue:white = 2:3. The total group contains 5 squares, so blue:all = 2:5. Confusing these comparisons changes the result. Write the names in the same order as the ratio numbers.

A scale factor multiplies every corresponding quantity by the same amount. Doubling this pattern gives 4 blue and 6 white squares, not 4 blue and 3 white. The new group has twice as many pieces but the same color proportion. Proportionality assumes there are no fixed amounts or changed conditions hidden in the process.

WORKED EXAMPLE
A classroom pattern needs blue:white = 2:3 and 45 squares in total. One ratio group contains 2 + 3 = 5 squares. There are 45/5 = 9 groups. Blue requires 2 × 9 = 18 squares, and white requires 3 × 9 = 27. Check both conditions: 18 + 27 = 45, and 18/27 simplifies to 2/3.

If only 17 blue squares are available, complete ratio groups are limited by blue. Seventeen divided by 2 allows 8 complete groups with 1 blue square left. Eight groups use 16 blue and 24 white squares. The remainder does not become another complete group merely because white squares are abundant.

WHEN A RULE IS NOT PROPORTIONAL
Suppose arranging a paper display takes a fixed 10 minutes to prepare the workspace plus 2 minutes per group. Five groups take 10 + 5 × 2 = 20 minutes. Ten groups take 10 + 10 × 2 = 30 minutes, not 40. Doubling the number of groups did not double the fixed preparation time. Record fixed and variable parts separately.

UNIT RATES
A ratio such as 36 labels for 4 folders gives 9 labels per folder. That rate supports scaling only if each folder genuinely uses the same number. If one type needs twice as many labels, split the types into separate rows instead of applying an average without explanation.

PRACTICE LIMITS
Use colored paper or counters to check the examples. Do not transfer a classroom scaling rule to medication, disinfectant, food preservation, structural design or chemical work. Real procedures can depend on concentration, geometry, temperature and safety limits that proportional arithmetic alone does not establish.
""", (
            Exercise("A 2:3 blue:white paper pattern has 45 squares total. How many are blue?", "18", "blue squares",
                     "2 + 3 = 5 parts; 45/5 = 9 per part; 2 × 9 = 18 blue squares."),
            Exercise("Setup takes 10 minutes, then 2 minutes for each of 10 paper groups. Total time?", "30", "minutes",
                     "10 + 2 × 10 = 30 minutes. The fixed setup occurs once, not once per group."),
        ), ("measurement", "manufacturing")),
        Lesson("percentages-reserves", "Percentages, changes and reserves", "foundations: numbers", ("fractions-decimals",),
               "Calculate a percentage of a stated base and distinguish reserve fractions from percentage changes.", """
NAME THE BASE
Percent means per hundred. Ten percent is 10/100 = 0.10. To find p percent of a quantity, multiply that quantity by p/100. The original quantity is the base. Without knowing the base, a statement such as '20 percent less' is incomplete.

For a pretend supply of 80 classroom tokens, a 15 percent reserve is 80 × 0.15 = 12 tokens. The amount outside that reserve is 80 − 12 = 68, equivalently 80 × (1 − 0.15). The reserve is still part of the physical total. Do not subtract it twice if a later calculation already uses the available amount.

WORKED EXAMPLE
A paper order contained 120 sheets; a later order contains 150. The increase is 150 − 120 = 30 sheets. Relative to the earlier order, the percentage increase is 30/120 × 100 = 25 percent. Comparing the earlier quantity to the later one answers a different question: 30/150 × 100 = 20 percent smaller. Both can be correct because the base changed.

PERCENTAGE POINTS
If a classroom attendance fraction changes from 40 percent to 50 percent, it rose by 10 percentage points. The relative increase is (50 − 40)/40 × 100 = 25 percent. State which description you mean rather than treating 'points' and 'percent' as interchangeable.

REPEATED CHANGES
A 20 percent increase followed by a 20 percent decrease does not return to the original amount. Starting from 100, the increase gives 120. The decrease uses 120 as its base, so 120 × 0.80 = 96. For repeated proportional changes, multiply the factors: 1.20 × 0.80 = 0.96.

WHOLE ITEMS AND ROUNDING
A percentage can produce a fractional answer even when you need whole objects. Ten percent of 23 counters is 2.3 counters. A policy might reserve at least 10 percent, which requires 3 whole counters, leaving 20. That rounding rule belongs to the stated activity; it must not silently be assumed for every task.

WRITE THE ASSUMPTIONS
Record the base quantity, percentage, purpose, rounding policy and whether a reserve has already been deducted. These exercises explain arithmetic only. They do not choose an appropriate emergency reserve or justify reducing required food, water, medicine or other essential supplies.
""", (
            Exercise("Eighty tokens have a 15 percent reserve. How many tokens are outside that reserve?", "68", "tokens",
                     "80 × (1 − 15/100) = 80 × 0.85 = 68. The reserve is 12 tokens."),
            Exercise("An order rises from 120 to 150 sheets. What is the percentage increase, entering only the number?", "25", "percent",
                     "The increase is 30 sheets; the original base is 120. 30/120 × 100 = 25 percent."),
        ), ("inventory",)),
        Lesson("length-conversions", "Convert lengths without losing units", "foundations: measurement", ("ratios-scaling",),
               "Use explicit conversion factors and distinguish a unit conversion from a new measurement.", """
KEEP A UNIT ON EACH LINE
A measurement combines a number and a unit. Changing the unit changes the number used to describe the same length; it does not make a new physical measurement. A long list of decimal digits from conversion does not improve the quality of the original measurement.

For these lessons, use the metric relationships 1 m = 100 cm = 1000 mm. The prefix kilo means a factor of 1000, centi means one hundredth, and milli means one thousandth. For example, 2.4 m = 240 cm = 2400 mm. Write a leading zero for a decimal less than one, such as 0.6 m, so a faint decimal point is less likely to be overlooked.

CONVERSION AS CANCELLATION
Set up a factor equal to one with the unwanted unit in the denominator. To convert 350 cm to metres: 350 cm × (1 m / 100 cm) = 3.5 m. Centimetres cancel. To convert back: 3.5 m × (100 cm / 1 m) = 350 cm. If the units do not cancel as intended, reverse the conversion factor before doing arithmetic.

WORKED EXAMPLE
For ordinary international-foot/inch lengths, 1 inch = 25.4 mm exactly and 1 foot = 0.3048 m exactly. A drawing line specified as 18 inches corresponds to 18 × 25.4 = 457.2 mm. A line specified as 3 feet corresponds to 3 × 0.3048 = 0.9144 m. These are exact conversions of the stated numbers, not claims about how precisely someone drew or measured the line.

Do not mix these examples with legacy surveying units, map coordinates or boundary work. Preserve the original unit definition in inherited records and obtain the relevant surveying information. This is not a geodetic conversion tool.

ADD AFTER CONVERTING
A paper layout uses 0.8 m plus 25 cm. Convert 25 cm to 0.25 m, then add to get 1.05 m. Adding 0.8 and 25 directly would combine unlike units. The same principle applies when comparing dimensions from different labels.

RELATED PREFIX REFERENCE
NIST — Metric (SI) Prefixes: https://www.nist.gov/pml/owm/metric-si-prefixes
This link identifies unit conventions, not a review of the lesson.

CHECK THE SCALE
Converting metres to millimetres makes the numerical value larger because millimetres are smaller units. Converting millimetres to metres makes it smaller. Keep original readings alongside converted values, state any rounding, and do not use these paper exercises to approve a safety-critical dimension or component fit.
""", (
            Exercise("Convert 3.6 m to millimetres.", "3600", "mm",
                     "3.6 m × 1000 mm/m = 3600 mm. The numerical value grows because the unit gets smaller."),
            Exercise("Convert an exact stated length of 18 inches using 25.4 mm per inch.", "457.2", "mm",
                     "18 × 25.4 = 457.2 mm. Conversion precision does not improve a real measurement's accuracy."),
        ), ("measurement", "construction"),
               "NIST — SI conversion factors, Appendix B.8; related unit reference, not lesson endorsement",
               "https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b8"),
        Lesson("perimeter-area", "Perimeter, area and layout", "foundations: measurement", ("length-conversions",),
               "Choose the right quantity for an edge or a surface and calculate simple paper-layout areas.", """
EDGES ARE NOT SURFACES
Perimeter is the distance around a shape. Area measures the surface it covers. For a rectangle of length L and width W, perimeter = 2 × (L + W), while area = L × W. Perimeter uses a length unit such as metres; area uses a squared unit such as square metres. Multiplying two lengths is what produces that squared unit.

A quick drawing helps prevent using the wrong measurement. Write dimensions along their corresponding edges. Draw cutouts and overlapping sections explicitly. Area alone does not tell you whether one particular shape will fit inside another, or whether a purchased sheet can be cut into all required pieces.

WORKED EXAMPLE
A paper rectangle represents a 2.4 m by 1.5 m display surface. Its perimeter is 2 × (2.4 + 1.5) = 7.8 m. Its area is 2.4 × 1.5 = 3.6 m². If a rectangular opening of 0.6 m by 0.5 m is excluded, subtract 0.6 × 0.5 = 0.3 m², leaving 3.3 m² of surface. The opening changes the boundary too, but subtracting area does not calculate any new edging requirement.

TRIANGLES AND CIRCLES
A triangle's area is one half of its base times its perpendicular height. The sloping side is not generally that height. A circle's area is πr², where r is the radius; its circumference is 2πr. Diameter is twice radius. For rough classroom arithmetic using π = 3.14, a paper circle of radius 0.5 m has area 3.14 × 0.5 × 0.5 = 0.785 m². State that approximation instead of presenting it as an exact value of π.

SQUARE UNITS SCALE TWICE
Since 1 m = 100 cm, one square metre is 100 cm × 100 cm = 10,000 cm², not 100 cm². Draw a square with both dimensions labeled to see why the factor is squared.

PLANNING A CUT LIST
Make a separate row for every piece: count, length, width, orientation and area. Try arranging paper rectangles within a larger paper sheet. You may discover unusable offcuts even when total required area is below total sheet area. Any allowance for waste is a chosen assumption, not a universal rule. These calculations do not establish structural strength, building compliance or load capacity.
""", (
            Exercise("A 2.4 m × 1.5 m rectangle has a 0.6 m × 0.5 m opening. What surface area remains?", "3.3", "m²",
                     "2.4 × 1.5 − 0.6 × 0.5 = 3.6 − 0.3 = 3.3 m²."),
            Exercise("What is the perimeter of the original 2.4 m × 1.5 m rectangle, ignoring the opening?", "7.8", "m",
                     "2 × (2.4 + 1.5) = 2 × 3.9 = 7.8 m. This is a length, not an area."),
        ), ("measurement", "construction")),
        Lesson("volume-capacity", "Volume, capacity and cubic units", "foundations: measurement", ("perimeter-area",),
               "Convert a rectangular internal volume into a stated capacity without assuming real-world usability.", """
THREE DIMENSIONS
The ideal volume of a rectangular box is internal length × internal width × internal height. Use the same length unit for all three. Multiplying three lengths produces a cubic unit. External dimensions include the walls and therefore do not directly give the internal capacity.

For volume conventions, 1 L = 1 dm³ = 1000 cm³, and 1 mL = 1 cm³. One cubic metre is 1000 L. The conversion grows with three dimensions: a metre cube is 100 cm on each edge, so it contains 100 × 100 × 100 = 1,000,000 cm³. The letter L helps distinguish litre from the digit 1 in a record.

WORKED EXAMPLE
A drawing shows an ideal internal box 40 cm long, 30 cm wide and 25 cm high. Its geometric volume is 40 × 30 × 25 = 30,000 cm³. Dividing by 1000 cm³/L gives 30 L. If the paper exercise specifies filling only to an internal depth of 20 cm, the corresponding volume is 40 × 30 × 20 = 24,000 cm³ = 24 L.

This does not say the box is suitable for holding a liquid, a particular load, food or drinking water. Rounded corners, taper, fittings, free space and manufacturer's operating limits can all matter. Capacity arithmetic is not a material compatibility or safety assessment.

PARTIAL CAPACITY AND LABELS
A container labeled 2 L does not necessarily contain 2 L at the moment you inspect it. Separate nominal capacity from recorded contents. A set of 6 labeled 2 L containers has 12 L of nominal combined capacity. Its actual usable contents remain unknown until appropriately established. Never silently treat unknown contents as full.

MASS IS ANOTHER QUANTITY
Litres measure volume, while kilograms measure mass. Converting between them requires a density for the actual material and conditions. 'One litre equals one kilogram' is not a general conversion rule. Do not use a volume example to infer the load a shelf or lifting system can carry.

PAPER PRACTICE
Sketch a box, label its three internal dimensions, and write the full units through each multiplication and conversion. Change only the height and explain why doubling that height doubles the ideal volume, whereas doubling every dimension multiplies volume by eight. Record geometric assumptions and do not convert the drawing into an equipment-use approval.
""", (
            Exercise("An ideal box is internally 40 cm × 30 cm × 25 cm. Convert its volume to litres.", "30", "L",
                     "40 × 30 × 25 = 30,000 cm³; divide by 1000 cm³/L to obtain 30 L."),
            Exercise("The same ideal box is filled to an internal depth of only 20 cm. What volume does the drawing represent?", "24", "L",
                     "40 × 30 × 20 = 24,000 cm³ = 24 L. Actual equipment suitability is not established."),
        ), ("measurement", "inventory"), "NIST — SI Units: Volume; related unit reference, not lesson review",
               "https://www.nist.gov/pml/owm/si-units-volume"),
        Lesson("measurement-uncertainty", "Measurements, repeats and uncertainty", "foundations: measurement", ("length-conversions",),
               "Separate repeatability, instrument resolution and uncertainty instead of inventing precision.", """
A MEASUREMENT NEEDS A METHOD
Record what is being measured, the chosen reference points, the tool and its smallest displayed division. Keep the tool aligned with the intended dimension. Looking from different angles can change a reading when a pointer or scale is separated from the object. Repeating a careless method may reproduce the same mistake.

Resolution is the smallest increment an instrument displays or marks. Repeatability describes how closely repeated measurements agree under similar conditions. Neither by itself proves closeness to the true value. A ruler whose starting edge is damaged could produce consistent readings with a systematic offset.

WORKED EXAMPLE
Three classroom measurements of a paper model's edge are 19.8 cm, 20.0 cm and 20.2 cm. Their mean is (19.8 + 20.0 + 20.2)/3 = 20.0 cm. Their range is maximum minus minimum: 20.2 − 19.8 = 0.4 cm. Report the individual observations too. The range summarizes this small set; it is not automatically a confidence interval or a complete uncertainty estimate.

Before averaging, check whether everyone measured the same edge using the same reference points. If one person included a tab and another did not, averaging their results hides a definition problem instead of solving it.

SIMPLE BOUNDS
For a fictional interval exercise, suppose two lengths are given as 10.0 ± 0.1 cm and 5.0 ± 0.1 cm, where ± is explicitly defined as a hard bound for the exercise. The sum lies between 9.9 + 4.9 = 14.8 cm and 10.1 + 5.1 = 15.2 cm. A compact report is 15.0 ± 0.2 cm. This worst-case interval addition is not a universal statistical uncertainty method. Real uncertainty work needs justified assumptions about the sources of error.

ROUNDING IS A REPORTING CHOICE
Keep extra digits while calculating, then round according to a stated rule appropriate to the measurement. Do not report a rough tabletop length to six decimal places simply because a calculator displays them. Also do not discard an original reading: keep raw observations and the reported summary separately.

SAFE PRACTICE
Compare measurements of harmless paper objects. Ask a second learner to repeat your written method without verbal help. Note disagreements, investigate their cause, and revise the method. This lesson does not certify a measuring tool or establish tolerances for structures, pressure systems, medicines or safety-critical parts.
""", (
            Exercise("The readings are 19.8, 20.0 and 20.2 cm. What is their arithmetic mean?", "20", "cm",
                     "The sum is 60.0 cm; 60.0/3 = 20.0 cm. The mean does not certify accuracy."),
            Exercise("Under the stated hard bounds, what is the maximum sum of 10.0 ± 0.1 cm and 5.0 ± 0.1 cm?", "15.2", "cm",
                     "Use both upper bounds: 10.1 + 5.1 = 15.2 cm. These are stipulated bounds, not inferred confidence limits."),
        ), ("measurement", "instrumentation", "scientific-method")),
        Lesson("scale-coordinates", "Scale drawings and local coordinates", "foundations: measurement", ("ratios-scaling", "length-conversions"),
               "Read a stated drawing scale and locate positions on a clearly defined classroom grid.", """
SCALE IS A RATIO OF LENGTHS
A drawing at 1:50 means one drawing length represents fifty of the same length units on the represented object. A 4 cm line represents 4 × 50 = 200 cm = 2 m. If the drawing is resized when copied or printed, that relationship may no longer hold. A scale bar reproduced with the drawing is useful for detecting resizing, but you still need to check it against the actual print.

Do not carry length scale factors straight into area or volume. At 1:50, the represented area corresponding to a small drawing square is multiplied by 50² = 2500. The represented volume factor would be 50³. The geometry lesson explains why there is one factor for each dimension.

WORKED EXAMPLE
A classroom layout uses scale 1:25. A rectangular table is drawn 6 cm long and 3 cm wide. The represented dimensions are 150 cm by 75 cm, or 1.5 m by 0.75 m. Its represented area is 1.5 × 0.75 = 1.125 m². The drawn area is 18 cm², and 18 × 625 = 11,250 cm² = 1.125 m² gives the same result.

DEFINE THE GRID
For a local paper grid, choose an origin labeled (0, 0). State which direction makes x increase and which makes y increase. Coordinates (x, y) give two ordered numbers: reversing them generally identifies a different location. Write the unit or grid spacing and define whether a coordinate identifies a corner, a center or another reference point.

On a practice grid with rightward x and upward y, points (2, 1) and (7, 4) differ by 5 units horizontally and 3 vertically. The straight-line distance is not 5 + 3; that sum describes one right-angle route. This lesson asks only for coordinate differences, so no distance formula is needed.

AVOID REAL-WORLD CONFUSION
A classroom grid is not latitude/longitude, a survey datum, or a navigational map. It cannot establish a property boundary, safe route, terrain clearance or evacuation path. Add orientation, scale, revision and a drawing key so the next reader understands the limited purpose.

TEACH-BACK
Have a learner place paper objects on your grid using written coordinates. Then move the origin and show how the same physical position receives different coordinates. Keep the old and new definitions visible; a number without its coordinate system is incomplete information.
""", (
            Exercise("At scale 1:25, a line on paper is 6 cm long. What length in metres does it represent?", "1.5", "m",
                     "6 × 25 = 150 cm; 150/100 = 1.5 m."),
            Exercise("A local grid moves from (2, 1) to (7, 4). What is the increase in x?", "5", "grid units",
                     "The horizontal coordinate change is 7 − 2 = 5. This is not a route or straight-line distance."),
        ), ("measurement", "construction")),
        Lesson("time-rates", "Time, rates and feasible schedules", "foundations: planning", ("fractions-decimals",),
               "Convert elapsed time and distinguish production rate from fixed setup time.", """
CLOCK NOTATION IS NOT A DECIMAL
One hour contains 60 minutes. Therefore 1 hour 30 minutes = 1 + 30/60 = 1.5 hours, not 1.30 hours. Conversely, 1.25 hours = 1 hour plus 0.25 × 60 = 15 minutes. Keep clock times and elapsed durations in different columns.

A rate describes an amount per unit time. If a fictional paper-folding task produces 18 pieces in 30 minutes, its observed average rate is 18/30 = 0.6 pieces per minute, or 36 per hour. That observation does not guarantee the same rate for longer work, a different learner, or a different paper type.

WORKED EXAMPLE
An activity has 12 minutes of fixed preparation and then 3 minutes per completed model. For 8 models, idealized total time is 12 + 8 × 3 = 36 minutes. In a 60-minute slot, the model leaves 60 − 12 = 48 minutes after setup, enough for 48/3 = 16 complete models if all assumptions hold. Breaks, mistakes and interruptions need separate treatment; the calculation does not make them disappear.

SERIAL AND PARALLEL WORK
Some tasks must happen one after another. If cutting takes 10 minutes and assembling those same pieces takes 15, one person's uninterrupted sequence takes 25 minutes. Other tasks might overlap if there are independent people and materials. You cannot simply divide every schedule by the number of helpers: a shared tool, limited space or prerequisite can prevent parallel work.

CHECK THE DENOMINATOR
For amount = rate × time, the time unit must match the rate. A rate in pieces/hour multiplied by minutes is not yet a piece count. Convert 45 minutes to 0.75 hour first. A rate of 24 pieces/hour for 0.75 hour gives 18 pieces.

UNKNOWN OR VARIABLE RATES
Record the observation period and sample conditions. Try low, typical and high-duration cases rather than one unexplained number. If a rate is unknown, say so and run a harmless pilot activity; do not replace missing information with zero or infinite productivity.

A SIMPLE RECORD
Task / setup time / time per piece or observed rate / available people and tools / prerequisites / expected interruptions / planned finish / actual finish. Compare predictions with observations afterwards. These are scheduling exercises, not guarantees for travel, emergencies, critical equipment or human endurance.
""", (
            Exercise("Convert 1 hour 45 minutes to decimal hours.", "1.75", "hours",
                     "1 + 45/60 = 1.75 hours. Clock minutes use a base of 60, not 100."),
            Exercise("Setup takes 12 minutes and each paper model takes 3 minutes. How long for 8 models?", "36", "minutes",
                     "12 + (8 × 3) = 36 minutes under the stated idealized assumptions."),
        ), ("inventory", "manufacturing")),
        Lesson("stock-ledger", "A stock ledger that balances", "foundations: planning", ("counting-units", "checking-arithmetic"),
               "Reconcile receipts, issues and adjustments without deleting unexplained differences.", """
THE BALANCE EQUATION
Closing stock = opening stock + received stock − issued stock + signed adjustments. Every term must use the same counting unit and refer to the same defined period and stock category. An adjustment is a documented correction, not a way to make inconvenient differences vanish.

Keep separate records for different sizes or types when they cannot be exchanged directly. Ten small notebooks and ten large notebooks are twenty notebooks by count, but that combined count does not tell you how many large notebooks remain. Record location and condition when those distinctions matter to the task.

WORKED EXAMPLE
A classroom ledger begins with 85 blank cards. During the day, 24 cards are received and 37 are issued. The calculated closing balance is 85 + 24 − 37 = 72 cards. A physical recount finds 70. The difference is counted minus calculated = 70 − 72 = −2 cards. Record the discrepancy and investigate duplicate entries, missed issues, wrong units or counting errors. Do not immediately conclude theft or loss without evidence.

If a recount and record review establish that an issue of 2 cards was missed, add a dated correction explaining that issue. Keep enough history that another reader can reconstruct why the total changed. In FieldForge, a stock adjustment and its reason are distinct from deleting an inventory record; use the workflow that reflects what actually happened.

LOTS, LOCATIONS AND TRANSFERS
Moving 10 items from shelf A to shelf B changes two location balances but not the combined total. Record one transfer identifier so you can match the decrease and increase. Receiving new stock is different: it changes the total held. Counting the same transfer as both a receipt to the organization and a location transfer inflates inventory.

ZERO, UNKNOWN AND UNUSABLE
A known count of zero is useful information. An uncounted shelf is unknown, not empty. A damaged item may exist physically but be excluded from a usable-stock count. State that rule and keep exclusions visible so later learners do not compare incompatible totals.

PAPER PRACTICE
Use counters and two labeled envelopes as locations. Ask one learner to move counters and another to keep the ledger. Compare calculated balances with a physical count, then intentionally omit a transfer and diagnose the disagreement. Use fictional data in a shared example. A balanced ledger proves arithmetic consistency under its inputs, not that real goods are safe, adequate or correctly identified.
""", (
            Exercise("Opening stock is 85 cards, receipts are 24, and issues are 37. What is the calculated closing balance?", "72", "cards",
                     "85 + 24 − 37 = 72 cards, before any justified adjustment."),
            Exercise("The physical count is 70 and the calculated balance is 72. What is counted minus calculated?", "-2", "cards",
                     "70 − 72 = −2 cards. This flags a discrepancy; it does not establish its cause."),
        ), ("inventory", "maintenance")),
        Lesson("stock-duration", "Estimate stock duration without false certainty", "foundations: planning", ("percentages-reserves", "time-rates", "stock-ledger"),
               "Calculate duration under stated usage assumptions and compare scenarios without prescribing rationing.", """
DEFINE THE MODEL
For a constant-use model, duration = available amount / amount used per day. The word available must already have a clear meaning: counted, appropriate for the stated purpose, with exclusions and any chosen reserve accounted for. Days is the resulting unit because items divided by items/day cancels to days.

This model is deliberately simple. It does not establish actual needs or justify reducing anyone's required supplies. The examples use classroom labels. Water, food, medications, medical equipment and other essentials require appropriate plans and guidance outside this arithmetic lesson.

WORKED EXAMPLE
A workshop exercise has 240 labels. A stipulated 10 percent reserve leaves 240 × 0.90 = 216 labels for routine activity. At 18 labels/day, modeled duration is 216/18 = 12 days. At 27 labels/day, it is 216/27 = 8 days. Both calculations use the same available quantity; the usage assumption changed.

The reserve has already been removed from 216. Applying another 10 percent deduction would double-count it. Keep the original physical quantity, reserve and routine available amount as separate labeled entries.

PARTIAL DAYS
If 100 labels remain and 24 are used per full activity day, the idealized ratio is 100/24 = 25/6 days, about 4.17. For scheduling complete 24-label days, only 4 complete days fit, with 4 labels remaining. Whether a fractional day is useful depends on the activity. State the interpretation rather than rounding up to a full day without explanation.

VARIABLE USE AND REPLENISHMENT
If known usage differs each day, subtract the planned daily quantities in sequence instead of assuming a constant rate. Future deliveries are expectations, not stock already on hand. Show a no-delivery scenario alongside any delivery-dependent scenario, and identify when the prediction stops being supported by the recorded data.

TRIGGERS FOR RECOUNTING
Recalculate when physical stock, exclusions, usage or expected timing changes. A simple worksheet contains counted date, opening available quantity, observed use, model assumptions, low/high-use cases and next review date. Mark unknown daily use as unknown; dividing by zero or presenting 'unlimited' is not a reasonable substitute.

TEACH-BACK
Ask a learner to explain why a perfect division cannot rescue an incorrect count or an inappropriate consumption assumption. Have them identify which input change would shorten the estimate most. Keep the result labeled as a scenario calculation rather than a promise of preparedness.
""", (
            Exercise("There are 240 labels with a stipulated 10 percent reserve. At 18 labels/day, what is the modeled duration?", "12", "days",
                     "240 × 0.90 = 216 labels; 216/18 = 12 days. The reserve is deducted once."),
            Exercise("Using the same 216 available labels at 27 labels/day, what is the modeled duration?", "8", "days",
                     "216/27 = 8 days. Higher use shortens duration without changing the physical count."),
        ), ("inventory",)),
        Lesson("energy-arithmetic", "Power and energy on paper", "foundations: planning", ("time-rates", "percentages-reserves"),
               "Distinguish watts from watt-hours and calculate an explicitly idealized energy budget.", """
POWER IS A RATE, ENERGY IS AN AMOUNT
A watt describes a rate of energy transfer. A watt-hour is the energy corresponding to one watt sustained for one hour. In a constant-power example, energy in Wh = power in W × duration in hours. Dividing available output energy by a constant load power gives an idealized duration.

This is a paper arithmetic lesson, not a wiring, battery-building, generator-operation or life-support planning procedure. A result does not prove that equipment is compatible, can handle a starting surge, or is safe to connect. Use the actual equipment documentation and qualified assistance for real electrical work.

WORKED EXAMPLE
A fictional lamp uses a constant 8 W for 5 hours: 8 × 5 = 40 Wh. A separate device uses a constant 20 W for 3 hours: 20 × 3 = 60 Wh. Total energy demand in this model is 100 Wh. If both devices run at once, their combined modeled power is 28 W. Energy demand and simultaneous power answer different questions.

For another paper example, suppose 500 Wh is the nominal energy, a stated modeling factor of 0.8 converts it to usable output energy, and no other reserve is assumed. Usable output is 500 × 0.8 = 400 Wh. At a constant output load of 50 W, the ratio is 400/50 = 8 hours. The 0.8 factor is supplied for the exercise, not a recommendation for real equipment.

LOSSES AND BOUNDARIES
If a worksheet begins with energy already measured at the output, applying an additional output-loss factor would count those losses twice. Write where each quantity is measured: nominal rating, battery side or usable output. Temperature, condition, operating limits, variable demand and other equipment-specific effects are not established by a simple nameplate number.

INTERMITTENT LOADS
A device that operates for part of an hour may use less energy than one running continuously, but it may still need its full operating power while on. For a constant 30 W load active for 20 minutes, convert time to 1/3 hour and calculate 30 × 1/3 = 10 Wh. This does not describe its startup requirements.

PRACTICE RECORD
Device / documented or measured power / active time / calculated energy / simultaneous-use assumption / omitted effects. Compare the sum twice and preserve the original units. Never treat this exercise's result as a guarantee that a critical device will keep running.
""", (
            Exercise("A constant 8 W lamp runs for 5 hours and a 20 W device for 3 hours. Total modeled energy?", "100", "Wh",
                     "8 × 5 + 20 × 3 = 40 + 60 = 100 Wh. This does not test simultaneous-power or startup compatibility."),
            Exercise("The exercise gives 400 Wh of usable output energy and a constant 50 W load. Idealized duration?", "8", "hours",
                     "400 Wh / 50 W = 8 h. Usable output energy is given, so no extra loss is subtracted here."),
        ), ("power-budget",), "NIST SP 330, Section 2 — units of energy and power; not lesson review",
               "https://www.nist.gov/pml/special-publication-330/sp-330-section-2"),
        Lesson("rearranging-formulas", "Rearrange formulas and check dimensions", "foundations: planning", ("ratios-scaling", "perimeter-area", "time-rates"),
               "Solve for an unknown by preserving equality and verify the result against the original equation.", """
LET A LETTER STAND FOR ONE QUANTITY
A formula is a concise relationship, not a substitute for defining its terms. Write what each symbol means and its unit. In d = r × t, d might be produced pieces, r pieces/hour and t hours. In another context d could mean distance, so do not assume the same letter always has the same meaning.

An equation states that two expressions are equal. To preserve that equality, apply the same allowed operation to both sides. From A = L × W, dividing both sides by nonzero L gives W = A/L. The condition L ≠ 0 matters because division by zero is undefined.

WORKED EXAMPLE
A rectangular paper layout must have area A = 12 m² and length L = 4 m in the represented dimensions. Its width is W = A/L = 12 m² / 4 m = 3 m. Substitute back: L × W = 4 m × 3 m = 12 m². The unit calculation agrees too: area divided by length leaves length.

For a simple schedule T = S + n × p, let total time T = 38 minutes, fixed setup S = 8 minutes and time per piece p = 5 minutes/piece. Subtract setup first: T − S = n × p. Divide by p: n = (38 − 8)/5 = 6 pieces. Dividing all 38 minutes by 5 would incorrectly treat setup time as productive piece time.

A DIMENSION CHECK
Length plus area is not a meaningful sum in this model. Metres per second multiplied by seconds gives metres; metres divided by seconds gives a rate. Unit cancellation can expose a formula written upside down even when its arithmetic looks neat. It cannot prove that the underlying model applies to the real problem.

ZERO AND SIGN CHECKS
Ask whether the result should be positive, negative or zero. If a model of an available work interval gives negative productive time because setup exceeds the interval, it signals an infeasible plan rather than a negative number of completed pieces. Whole-piece requirements may also need a clear floor or ceiling rule after solving.

PAPER PRACTICE
Take a harmless rectangle formula and solve it three ways: for area, length and width. Make up compatible values, solve for one unknown, then substitute it back. Write the domain restrictions next to each division. This lesson does not derive engineering designs or authorize using simple equations beyond their stated assumptions.
""", (
            Exercise("A rectangular paper-layout model has area 12 m² and length 4 m. What is its width?", "3", "m",
                     "W = A/L = 12/4 = 3 m. Substitution gives 4 × 3 = 12 m²."),
            Exercise("A 38-minute slot includes 8 minutes of setup and 5 minutes per piece. How many complete pieces fit exactly?", "6", "pieces",
                     "n = (T − S)/p = (38 − 8)/5 = 30/5 = 6 pieces."),
        ), ("measurement", "manufacturing")),
        Lesson("tables-graphs", "Tables and graphs that show the data honestly", "foundations: records", ("time-rates",),
               "Organize observations with units, distinguish cumulative totals from daily amounts, and label a graph.", """
ONE ROW, ONE DEFINED OBSERVATION
Choose what each row means before collecting values. A row might be one day, one object or one repeated measurement. Put units in the column headings and state the observation period. Keep categories separate from quantities: a location name is not a number to average.

Missing data and zero are different. A blank or a clear 'not measured' entry means a value is unknown. Writing zero instead can change totals, averages and a graph's apparent pattern. Record the source and any exclusions so another learner can reconstruct the table.

WORKED EXAMPLE
A classroom activity completes 3, 5, 4 and 8 paper pieces on days 1 through 4. The daily counts are those four values. The cumulative totals are 3, 8, 12 and 20. A cumulative line can never decrease if you are only adding nonnegative completions, whereas daily production can rise or fall. Label which series you plot.

The increase in the cumulative total from the end of day 2 to the end of day 4 is 20 − 8 = 12 pieces. That change covers two days. Its average rate is 12/2 = 6 pieces/day for that interval, not necessarily the rate on either individual day.

DRAWING THE GRAPH
Place the independent sequence, such as day number, on one axis and the measured count on the other. Mark consistent spacing and write units or category labels. Include a title that identifies the activity and dates. A bar chart suits separate daily counts; a line can show ordered observations, but connecting points does not create measurements between them.

Avoid making unequal numerical intervals look equally spaced. If an axis starts above zero, label it clearly and consider how it changes the visual impression of differences. Preserve the raw table beside the graph so the reader can inspect actual values rather than relying on appearance alone.

WHAT A PATTERN DOES NOT PROVE
A rising line does not by itself explain a cause or guarantee future increases. A new material, a different number of participants or a changed counting rule may explain part of a difference. Write those context changes in a separate note. Extrapolating beyond the observed range requires assumptions, not just a longer ruler.

TRY IT
Draw both daily and cumulative counts from the same four-day example. Ask another learner to identify which one answers 'How many today?' and which answers 'How many so far?' Discuss how a missing day would need to be shown rather than quietly invented.
""", (
            Exercise("Daily paper-piece counts are 3, 5, 4 and 8. What is the cumulative total after day 4?", "20", "pieces",
                     "3 + 5 + 4 + 8 = 20 pieces. This is a cumulative total, not day 4 alone."),
            Exercise("Cumulative output is 8 at day 2 and 20 at day 4. What is the average increase per day across that interval?", "6", "pieces/day",
                     "(20 − 8)/(4 − 2) = 12/2 = 6 pieces/day. Individual daily rates may differ."),
        ), ("measurement", "scientific-method")),
        Lesson("averages-variation", "Averages, ranges and uneven samples", "foundations: records", ("fractions-decimals", "tables-graphs"),
               "Calculate a mean, median and range while preserving observations and recognizing unequal group sizes.", """
ONE SUMMARY DOES NOT DESCRIBE EVERYTHING
The arithmetic mean is the sum of values divided by the number of values. The median is the middle value after sorting; for an even number of observations it is the mean of the two middle values. The range is maximum minus minimum. Each answers a different question about the same data.

Use quantities with the same meaning and unit. Averaging a length, a temperature and a piece count because they are all numbers produces no useful physical result. Even within one unit, check that observations were made under comparable definitions and conditions.

WORKED EXAMPLE
Five fictional paper-folding durations are 4, 5, 5, 6 and 20 minutes. Their sum is 40 minutes, so the mean is 40/5 = 8 minutes. Sorted order is already shown; the median is 5 minutes. The range is 20 − 4 = 16 minutes. The mean is higher than most observations because the 20-minute observation contributes substantially to the sum.

Do not delete the 20-minute value simply to make the result look more regular. Investigate it. Was it a transcription error, an interruption, or a genuine slow attempt under the stated rules? Keep the original value and document any justified correction or separate analysis.

GROUPS OF DIFFERENT SIZE
Suppose one group has 2 learners whose total practice time is 12 minutes, and another has 8 learners whose total is 24 minutes. The group means are 6 and 3 minutes. Averaging those means without weights gives 4.5, but the combined learner mean is (12 + 24)/(2 + 8) = 36/10 = 3.6 minutes. Use group sizes or original totals when combining group means.

SAMPLES AND MISSING INFORMATION
A small convenient sample may not represent other people, tasks or conditions. The computed mean is exact for the supplied arithmetic inputs, not a guaranteed prediction for the next observation. Missing observations cannot silently be filled with the mean or zero without changing the meaning of the analysis.

REPORT A USEFUL SUMMARY
Give the observation count, units, raw data or a recoverable source, summary method and relevant context. Show both a typical value and variation when useful. This lesson is introductory arithmetic, not statistical evidence of treatment effectiveness, safety, population characteristics or a professionally validated performance standard.

TEACH-BACK
Make two different five-value datasets with the same mean. Compare their ranges and discuss why identical means do not imply identical patterns.
""", (
            Exercise("For durations 4, 5, 5, 6 and 20 minutes, what is the arithmetic mean?", "8", "minutes",
                     "The sum is 40 minutes for 5 observations, so mean = 40/5 = 8 minutes."),
            Exercise("Two learners total 12 practice minutes and eight others total 24. What is the mean across all ten learners?", "3.6", "minutes per learner",
                     "Use total minutes divided by total learners: (12 + 24)/(2 + 8) = 36/10 = 3.6."),
        ), ("measurement", "scientific-method")),
        Lesson("fair-comparisons", "Plan a fair, harmless comparison", "foundations: records", ("measurement-uncertainty", "tables-graphs"),
               "Separate a testable question, an observation and a causal conclusion in a paper-based experiment.", """
ASK ONE LIMITED QUESTION
A useful classroom question names what will change, what will be measured and under what conditions. For example: 'For this paper-folding exercise, does instruction sheet A or B lead to fewer counting mistakes on the same sample pattern?' That is narrower than 'Which teaching method is best for everyone?'

Define the outcome before seeing results. Is a mistake a missing fold, a wrong count or a missed label? Choose a rule a second observer can apply. A measurement rule changed halfway through a comparison can create an apparent difference that belongs to the rule, not the instruction sheet.

KEEP OTHER CONDITIONS VISIBLE
Use the same paper, pattern, time allowance and definition of a completed attempt where appropriate. Prior practice, fatigue and order can matter. If every learner uses A first and B second, B may benefit from practice. Varying or balancing order can help examine that problem, but does not automatically eliminate every confounder.

WORKED EXAMPLE
In a fictional record, condition A produces 18 correctly counted patterns out of 20 attempts. Condition B produces 16 out of 20. The observed success fractions are 18/20 = 90 percent and 16/20 = 80 percent, a difference of 10 percentage points. Those arithmetic facts alone do not prove A is generally better. The attempts may involve different learners, repeated trials, selection effects or ordinary variation.

Replicate the harmless exercise and record the procedure before deciding what conclusion the evidence supports. Keep unsuccessful attempts in the denominator unless a stated rule genuinely excludes them. Selecting only successful attempts makes a success fraction meaningless.

OBSERVATION VERSUS EXPLANATION
'Group A counted 18 patterns correctly' is an observation under a defined rule. 'A caused better learning' is an explanatory claim requiring additional reasoning and evidence. A correlation, before/after difference or visually attractive graph is not by itself a causal demonstration.

RECORD FOR REPEATING
Question / versions of the materials / measurement rule / participant aliases if necessary / ordering method / raw outcomes / deviations / analysis / unanswered questions. Keep personally identifying details out of a shared teaching packet unless genuinely needed and appropriately handled.

LIMITS
Use safe paper-and-pencil activities only. Do not turn this classroom design into unsupervised experiments on people, animals, medicines, food safety, electrical systems or hazardous substances. The lesson teaches record discipline and cautious interpretation, not research authorization or proof that a procedure is safe.
""", (
            Exercise("A fictional activity has 18 correct patterns out of 20 attempts. Enter its success percentage as a number.", "90", "percent",
                     "18/20 × 100 = 90 percent for these recorded attempts; no general causal conclusion follows."),
            Exercise("The recorded success rates are 90 percent and 80 percent. What is their difference in percentage points?", "10", "percentage points",
                     "90 − 80 = 10 percentage points. This is not the same wording as a relative percent increase."),
        ), ("scientific-method", "teaching")),
        Lesson("technical-records", "Write records another person can use", "foundations: records", ("stock-ledger", "measurement-uncertainty"),
               "Build a minimal traceable record that separates observations, assumptions and later corrections.", """
A RECORD SHOULD SURVIVE ITS AUTHOR
Imagine that another person must repeat a task without asking you what you meant. They need an identifiable object, a purpose, units, a method, a date or sequence, a result and the relevant limits. A confident sentence such as 'checked and fine' leaves nearly all of that information missing.

Use a stable local identifier for the object or worksheet, while keeping its human-readable name. Distinguish a model name, a particular individual asset and a particular document revision. Two objects with the same nickname may still need different records. A label alone does not establish authenticity or safety.

A SIMPLE TEMPLATE
Record ID:
Object or activity and version:
Purpose and scope:
Date/time convention and recorder alias:
Tool or source used:
Observed inputs with units:
Assumptions kept separate:
Calculation or method:
Result and uncertainty/limits:
Check performed and unresolved questions:
Correction history or next review:

WORKED EXAMPLE
A fictional inventory worksheet says: 'Record CARD-07; classroom cards; opening count 40 cards; received 12; issued 9; calculated closing 43; independently counted 42.' The arithmetic balance is 40 + 12 − 9 = 43. The one-card discrepancy is visible. Writing only '42 cards, checked' would conceal that disagreement and prevent diagnosis.

An appropriate follow-up records the recount or correction and its reason. Keep observation separate from inference: 'counted 42' is not the same claim as 'one card was lost'. Do not invent a missing explanation to make a record feel complete.

SOURCE AND REVISION DISCIPLINE
When a worksheet depends on another document, note its title, exact version if known and where a retained copy can be found. A URL alone is not an offline copy. A file checksum helps identify a byte sequence, but does not establish that the advice is right or the publisher genuine. When replacing a source, preserve enough context to identify which results relied on the earlier version.

PRIVACY AND SHARING
Use fictional examples or aliases for practice. Keep passwords, unnecessary personal identifiers and private health information out of articles intended for sharing. A reusable blank template can be public while a filled-in record is private. Decide that distinction before exporting.

TEACH-BACK
Exchange a fictional filled-in record with a learner. Ask them to reproduce the arithmetic and list every assumption they had to guess. Revise the form until those guesses are either supplied or explicitly marked unknown. This improves documentation; it is not equipment inspection, clinical review or professional sign-off.
""", (
            Exercise("A record starts with 40 cards, receives 12 and issues 9. What closing balance should the arithmetic show?", "43", "cards",
                     "40 + 12 − 9 = 43 cards. A physical count is a separate observation to compare."),
            Exercise("The physical count is 42 and the calculated balance is 43. What is the magnitude of the discrepancy?", "1", "card",
                     "The signed difference is −1 card; its magnitude is 1. The arithmetic does not identify a cause."),
        ), ("records", "maintenance", "teaching")),
        Lesson("teach-back-capstone", "Capstone: plan and teach a paper workshop", "foundations: records", ("stock-duration", "energy-arithmetic", "averages-variation", "technical-records"),
               "Combine counts, units, a schedule and a reproducible explanation in a harmless worked project.", """
THE PROJECT
Plan a fictional classroom session making paper models. The purpose is to use the pack's arithmetic and documentation skills together, not to build a structure or certify competence. Keep all activity quantities in one worksheet, with separate sections for materials, timing, optional modeled energy and actual observations.

STATE THE GIVEN INPUTS
There are 8 learners. Each makes 3 models. Each model needs 2 paper sheets. A stipulated classroom reserve adds 8 unused sheets. Setup takes 10 minutes. For the simplified schedule, assume one learner makes one model in 5 minutes and all 8 learners work concurrently with independent materials. Real learners may take different times; this is a stated model, not a productivity requirement.

WORKED PLAN
Required models = 8 × 3 = 24. Sheets consumed by models = 24 × 2 = 48. Adding the separately stated reserve gives 48 + 8 = 56 sheets to prepare. Do not multiply the reserve by the number of learners unless the instructions explicitly define it per learner.

Under the parallel-work assumption, each learner's 3 models take 3 × 5 = 15 minutes. Add the shared 10-minute setup to get 25 minutes before any extra cleanup, breaks or interruptions. If one person instead made all 24 models sequentially at the same rate, modeled time would be 10 + 24 × 5 = 130 minutes. Those schedules answer different resource-allocation questions.

MAKE A CHECKABLE LESSON
Write one observable learning goal: 'The learner can count the sheets required, state the reserve separately and explain the timing assumptions.' Demonstrate the calculation using counters before anyone starts. Ask the learner to do a different example, not merely repeat the same numbers. Have them explain why a per-model quantity multiplies by model count while fixed setup occurs once.

OBSERVE AND REVISE
Record actual sheet use, completed model counts and elapsed times using the same definitions. If outcomes differ, investigate assumptions: shared tools, rework, interruptions, changed model design or counting mistakes. Do not mark a learner incapable because an idealized plan failed. Preserve the original prediction beside the observation and document any revision.

RECORDING LEARNING
Keep learner responses private and minimal. A correct numeric answer demonstrates this exercise's arithmetic under its assumptions. It does not establish practical proficiency, professional qualifications, safety clearance or an ability to teach every subject. FieldForge's separate practice record remains a deliberate self-report; this pack never marks it complete automatically.

NEXT STEP
Choose one basic skill that still needs practice and repeat it with new harmless examples. Link useful installed readings to the corresponding Civilization Pathways goals deliberately. More advanced construction, agriculture, health, engineering and other work still needs appropriate source material, training and qualified oversight.
""", (
            Exercise("Eight learners make three models each. Each model uses two sheets; add an eight-sheet reserve. Total sheets to prepare?", "56", "sheets",
                     "8 × 3 × 2 + 8 = 48 + 8 = 56 sheets. The stated reserve is added once."),
            Exercise("Each learner works in parallel, making three models at five minutes each after a shared ten-minute setup. Modeled duration?", "25", "minutes",
                     "10 + 3 × 5 = 25 minutes under the independent parallel-work assumption, excluding unspecified extra tasks."),
        ), ("teaching", "inventory", "records")),
    )
