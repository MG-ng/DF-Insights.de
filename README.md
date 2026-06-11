# Dunkelflauten Insights




## Test and Deploy 

TODOs: 

- [ ] [Analyze your code for known vulnerabilities with Static Application Security Testing (SAST)](https://docs.gitlab.com/ee/user/application_security/sast/) 

***


## Suggestions for a good README 

Every project is different, so consider which of these sections apply to yours. The sections used in the template are suggestions for most open source projects. Also keep in mind that while a README can be too long and detailed, too long is better than too short. If you think your README is too long, consider utilizing another form of documentation rather than cutting out information. 


## Description 
This website lets you explore Dunkelflauten from different angles. 
Features: 
+ Time Series Chart 
+ Variable Moving Average 
+ Bubble Chart to compare Dunkelflauten 
+ Weather Map to analyse weather patterns 


## Support 
You can get my support by contacting me via [email](mailto:markus.gockel@tum.de) or via [LinkedIn](https://www.linkedin.com/in/markusgockel/). 


## Roadmap 
If you have ideas for releases in the future, let me know. 


## Contributing 
Contributions are welcomed. 

Create the local environment file before running the application:

```shell
cp .env.example .env
```

Then set the PostgreSQL credentials in `.env`. Existing shell environment
variables take precedence over the file. The old `DBP` variable remains
supported as a fallback for `DB_PASSWORD`.


## Authors and acknowledgment 
This project builds on top of APIs from SMARD and Open-Meteo 


## License 
No warranties provided. 


## Project status 
Almost all the features on the TODO List were achieved. 
Development of further functionality can be requested. 
Please reach out for more details! 
