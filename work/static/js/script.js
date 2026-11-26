"use strict"; // Turns on strict mode for this compilation unit: No implicit global variables possible
// if there is a typo in referencing a variable, without this, there would be created a new undefined

export { randomHSL, toast, loadingToast, unix_time_duration, getTurboColor }

console.log("Executing script.js……")


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
                background: "linear-gradient(to right, #49FCAF, #0D6EFD)",
            },
            onClick: function(){} // Callback after click
        }).showToast();
    }
}

function loadingToast() {
    return Toastify({
        text: " Data is loading... ",
        duration: -1,
        close: true,
        gravity: "bottom", // `top` or `bottom`
        position: "center", // `left`, `center` or `right`
        avatar: "/static/images/loading/6dotsLoading.gif",
        style: {
            background: "linear-gradient(to right, #49FCAF, #0D6EFD)",
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

function getTurboColor(t) {
    // t should be between 0 and 1
    t = Math.max(0, Math.min(1, t));

    const r = Math.max(0, Math.min(1,
        34.61 + t * (1172.33 + t * (-10793.56 + t * (33300.12 + t * (-38394.49 + t * 14825.05))))));
    const g = Math.max(0, Math.min(1,
        23.31 + t * (557.33 + t * (1225.33 + t * (-3574.96 + t * (1073.77 + t * 707.56))))));
    const b = Math.max(0, Math.min(1,
        27.2 + t * (3211.1 + t * (-15327.97 + t * (27814.0 + t * (-22569.18 + t * 6838.66))))));

    return `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
}
