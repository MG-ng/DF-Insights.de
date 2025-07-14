"use strict"; // Turns on strict mode for this compilation unit: No implicit global variables possible
// if there is a typo in referencing a variable, without this, there would be created a new undefined

export { randomHSL }

/*
export { variable1 as name1, variable2 as name2, …, nameN };
import { export1, export2 } from "module-name";
 */

// Stepped randomColor to have a visual distinction between the graph lines
// TODO: Create a function that avoids the same color for the same graph (Currently it's just unlikely)
function randomHSL() {
    var h = Math.floor(Math.random() * 360 /18) * 18; // hue: 0-360
    var s = Math.floor(Math.random() * 70 /20) * 20 + 30 + '%'; // saturation: 30-100%
    var l = Math.floor(Math.random() * 40 /10) * 10 + 40 + '%'; // brightness: 40-80%
    console.log(`color: hue = ${h}, saturation = ${s}, brightness = ${l}`)
    return `hsl(${h}, ${s}, ${l})`;
}



/**
 * const bigArray = new Array(1000000).fill(0);
 *
 * // Splice modifies in-place (memory efficient)
 * bigArray.splice(500000, 1); // Removes 1 element, shifts others
 *
 * // Slice creates new array (uses more memory)
 * const newArray = bigArray.slice(0, 500000); // Creates copy of 500k elements
 */