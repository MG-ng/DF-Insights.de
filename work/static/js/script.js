"use strict"; // Turns on strict mode for this compilation unit: No implicit global variables possible
// if there is a typo in referencing a variable, without this, there would be created a new undefined

export { randomHSL, toast, loadingToast, unix_time_duration }

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

function toast(message) {
    if (message) {
        Toastify({
            text: message,
            duration: 3000,
            close: true,
            gravity: "bottom", // `top` or `bottom`
            position: "center", // `left`, `center` or `right`
            stopOnFocus: true, // Prevents dismissing of toast on hover
            style: {
                background: "linear-gradient(to right, #00b09b, #96c93d)",
            },
            onClick: function(){} // Callback after click
        }).showToast();
    }
}

function loadingToast() {
    return Toastify({
        text: "Data is loading...",
        duration: -1,
        close: true,
        gravity: "bottom", // `top` or `bottom`
        position: "center", // `left`, `center` or `right`
        avatar: "https://icon-library.com/images/spinner-icon-gif/spinner-icon-gif-23.jpg",
        style: {
            background: "linear-gradient(to right, #188EEA, #2AA9EF)",
        },
        onClick: function(){} // Callback after click
    })
}


function unix_time_duration(duration, resolution) {
  let durationMs;
  switch (resolution) {
      case "hour":
          durationMs = duration * 60 * 60 * 1000; // milliseconds in an hour
          break;
      case "day":
          durationMs = duration * 24 * 60 * 60 * 1000; // milliseconds in a day
          break;
      case "week":
          durationMs = duration * 7 * 24 * 60 * 60 * 1000; // milliseconds in a week
          break;
      default:
          throw new Error("Invalid resolution. Must be 'hour', 'day', or 'week'.");
  }
  return durationMs;
}
