function updatePlaceHolder(input) {
    var usernameInput = document.getElementById(input);
    var placeholderParagraph = document.getElementById(input + 'placeholder');
    var hideshow = document.querySelector("#hideShow" + input);
    
    // Helper functions to add/remove classes
    function addPlaceholderClasses() {
        placeholderParagraph.classList.add('placeholderWithText');
        if (hideshow) {
            hideshow.classList.add('hideShowFucused');
        }
    }

    function removePlaceholderClasses() {
        placeholderParagraph.classList.remove('placeholderWithText');
        if (hideshow) {
            hideshow.classList.remove('hideShowFucused');
        }
    }

    // Initial state handling
    // Add classes only if the input is focused and empty or has a value
    if (usernameInput === document.activeElement && usernameInput.value === "") {
        addPlaceholderClasses();
    } else if (usernameInput.value !== "") {
        addPlaceholderClasses();
    } else {
        removePlaceholderClasses();
    }

    // Event listener for focus
    usernameInput.addEventListener('focus', function() {
        if (usernameInput.value === "") {
            addPlaceholderClasses();
        }
    });

    // Event listener for blur
    usernameInput.addEventListener('blur', function() {
        if (usernameInput.value === "") {
            removePlaceholderClasses();
        } else {
            addPlaceholderClasses();
        }
    });
}
// Put the IDs in an array. Like this: 'Test1', 'Test2'
// const exceptionIds = [
//];

function initializePlaceholders() {
    const inputs = document.querySelectorAll("input[id], select[id], textarea[id]");
    inputs.forEach(function(input) {
        if (!exceptionIds.includes(input.id)) {
            updatePlaceHolder(input.id);
        }
    });
}
initializePlaceholders();



var isPasswordVisible = false;

function togglePassword(input) {


    var hideshow = document.querySelector("#hideShow"+input)
      var passwordInput = document.getElementById(input);
        
      isPasswordVisible = !isPasswordVisible;
    
      if (isPasswordVisible) {
        passwordInput.type = 'text';
        hideshow.innerHTML = "Hide"
        hideshow.classList.add('hideShowUnder')
      } else {
        passwordInput.type = 'password';
        hideshow.innerHTML = "Show"
        hideshow.classList.remove('hideShowUnder')
      }
    }