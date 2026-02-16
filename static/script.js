document.addEventListener("DOMContentLoaded", function () {

    const form = document.getElementById("reviewForm");
    const loading = document.getElementById("loading");
    const result = document.getElementById("result");

    // Ensure loading is hidden on page load
    loading.classList.add("hidden");

    form.addEventListener("submit", async function (e) {
        e.preventDefault();

        const repoUrl = document.getElementById("repo_url").value;
        const fileInput = document.getElementById("roles_file").files[0];

        if (!repoUrl || !fileInput) return;

        const formData = new FormData();
        formData.append("repo_url", repoUrl);
        formData.append("roles_file", fileInput);

        loading.classList.remove("hidden");
        result.innerHTML = "";

        try {
            const response = await fetch("/review", {
                method: "POST",
                body: formData
            });

            const data = await response.json();

            loading.classList.add("hidden");

            result.innerHTML = `
                <strong style="font-size:18px;">Final Score</strong>
                <div style="margin:10px 0 25px 0; font-size:22px; font-weight:700; color:#2563eb;">
                    ${data.score}
                </div>

                <strong style="font-size:18px;">Enterprise Report</strong>
                <div style="margin-top:15px;">
                    ${data.report}
                </div>
            `;

        } catch (error) {
            loading.classList.add("hidden");
            result.innerText = "Error: " + error;
        }
    });

});
